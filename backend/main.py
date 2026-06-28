import os, json, uuid, random, asyncio, httpx, shutil
from PIL import Image
from enum import Enum
from fastapi import FastAPI, HTTPException, Depends, File, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from sqlalchemy.future import select
from sqlalchemy.ext.asyncio import AsyncSession
from database import SessionLocal, JobRecord, init_db

# Pull the ComfyUI URL from the environment variable set in docker-compose
COMFY_API_URL = os.environ.get("COMFY_API_URL", "http://127.0.0.1:8188")
COMFY_WS_URL = COMFY_API_URL.replace("http://", "ws://").replace("https://", "wss://")

# This decides what workflow/model to use
class ModelName(str, Enum):
    imagegen = "imagegen"
    imageedit = "imageedit"
    # add new workflow

# Maps the Enum->local JSON
WORKFLOW_MAP = {
    ModelName.imagegen: "image_z_image_turbo.json",
    ModelName.imageedit: "image_flux2_klein_image_edit_4b_base.json",
    # direct ModelName.new_workflow to JSON
}

# Used for JIT model warming
class WarmupRequest(BaseModel):
    model_name: ModelName

# Pydantic model for strict input validation
class GenerateRequest(BaseModel):
    model_name: ModelName
    query: str
    image_filename: str | None = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Initializing Database...")
    await init_db()

    # NEW: Safely generate a 256x256 black dummy image for FFmpeg compatibility
    input_dir = "/opt/ComfyUI/input"
    os.makedirs(input_dir, exist_ok=True)
    dummy_path = os.path.join(input_dir, "dummy_warmup.png")

    if not os.path.exists(dummy_path):
        # Creates a standard 256x256 RGB image
        img = Image.new('RGB', (256, 256), color='black')
        img.save(dummy_path)

    print("Database Ready!")
    yield

async def get_db():
    async with SessionLocal() as session:
        yield session
app = FastAPI(title="FastAPI_Portfolio", lifespan=lifespan)

# Allows the Reach frontend to communicate with FastAPI
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173","http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Set for job tracking (in memory)->switch to Redis(multi-pod))
#jobs_db = {}

# Dynamically loads the ComfyUI workflow JSON into memory from local directory.
def load_workflow(workflow: ModelName) -> dict:
    # Obtains filename from dictionary
    filename = WORKFLOW_MAP.get(workflow)

    if not filename:
        raise HTTPException(status_code=500, detail="Workflow not found for {workflow.value}")

    # Grabs filepath depending on OS file structure
    filepath = os.path.join("workflows", filename)

    try:
        with open(filepath, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail=f"Workflow not found.")

# For JIT model warming: Parses and modifies JSON to decrease steps and image size. (Loads model in VRAM with minimal output)
def prepare_warmup_workflow(workflow: dict) -> dict:
    """Dynamically finds and shrinks samplers/images for a lightning-fast warmup."""
    for node_id, node_data in workflow.items():
        class_type = node_data.get("class_type", "")
        inputs = node_data.get("inputs", {})

        # 1. Drop steps to 1 (ADDED "Scheduler" to catch your new Flux workflow!)
        if ("KSampler" in class_type or "Scheduler" in class_type) and "steps" in inputs:
            inputs["steps"] = 1

        # 2. Shrink the latent image so the GPU doesn't waste VRAM
        elif "LatentImage" in class_type and "width" in inputs:
            inputs["width"] = 256
            inputs["height"] = 256

        # 3. Inject a dummy prompt
        elif class_type == "CLIPTextEncode" and "text" in inputs:
            inputs["text"] = "warmup"

        # 4. NEW: Intercept the Image Node and inject our 1x1 dummy image
        elif class_type == "LoadImage" and "image" in inputs:
            inputs["image"] = "dummy_warmup.png"

    return workflow

# 
@app.post("/api/portfolio/warmup")
async def trigger_warmup(request: WarmupRequest):
    """Fires a 1-step dummy payload to load models into VRAM."""
    # 1. Load the specific workflow they clicked
    base_workflow = load_workflow(request.model_name)

    # 2. Modify it for a fast warmup
    warmup_workflow = prepare_warmup_workflow(base_workflow)

    payload = {
        "prompt": warmup_workflow,
        "client_id": f"warmup-{uuid.uuid4()}"
    }

    # 3. Fire and forget! Do not 'await' the full execution.
    asyncio.create_task(send_warmup_to_comfy(payload))

    # Immediately let the frontend continue loading the next page
    return {"status": "warming_up", "model": request.model_name.value}


async def send_warmup_to_comfy(payload: dict):
    """Background task to push the payload to ComfyUI."""
    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            await client.post(f"{COMFY_API_URL}/prompt", json=payload)
            print("🚀 Warmup payload sent to ComfyUI successfully.")
        except Exception as e:
            print(f"⚠️ Warmup request failed (server might be down): {e}")


@app.post("/api/portfolio/upload")
async def upload_image(file: UploadFile = File(...)):
    """Receives file from React and saves it to the ComfyUI input folder."""
    file_extension = file.filename.split(".")[-1]
    unique_filename = f"upload_{uuid.uuid4().hex}.{file_extension}"

    # This matches the physical folder on your server we mounted
    input_dir = "/opt/ComfyUI/input"
    os.makedirs(input_dir, exist_ok=True)
    file_path = os.path.join(input_dir, unique_filename)

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    return {"filename": unique_filename}


@app.post("/api/portfolio/imagegen")
async def queue_generation(request: GenerateRequest, db: AsyncSession = Depends(get_db)):
    workflow = load_workflow(request.model_name)
    seed_val = random.randint(1, 1000000000000000)
    job_id = str(uuid.uuid4())

    # --- CONDITIONAL JSON INJECTION ---
    if request.model_name == ModelName.imagegen:
        try:
            workflow["57:27"]["inputs"]["text"] = request.query
            workflow["57:3"]["inputs"]["seed"] = seed_val
            workflow["9"]["inputs"]["filename_prefix"] = job_id
        except KeyError as e:
            print(f"Warning: Node ID not found in imagegen JSON: {e}")

    elif request.model_name == ModelName.imageedit:
        try:
            # Flux Image-to-Image Nodes
            workflow["75:74"]["inputs"]["text"] = request.query
            workflow["75:73"]["inputs"]["noise_seed"] = seed_val
            workflow["9"]["inputs"]["filename_prefix"] = job_id  # Strict Contract reused!

            # Inject the uploaded filename into LoadImage (Node 76)
            if request.image_filename:
                workflow["76"]["inputs"]["image"] = request.image_filename
            else:
                raise HTTPException(status_code=400, detail="Image file required for edit workflow")
        except KeyError as e:
            print(f"Warning: Node ID not found in imageedit JSON: {e}")


    # Create unique client-side ID, replace with login
    client_id = str(uuid.uuid4())
    # loads payload with JSON containing (user prompt and node to file information) and unique id
    payload = {"prompt": workflow, "client_id": client_id}

    async with httpx.AsyncClient(timeout=10.0) as client:
        try: # Sends JSON payload to headless comfy. Submits through "/prompt" endpoint
            response = await client.post(f"{COMFY_API_URL}/prompt", json=payload)
            if response.status_code != 200:
                raise HTTPException(status_code=500, detail=f"ComfyUI rejected the workflow: {response.text}")
            response.raise_for_status()
        except httpx.RequestError:
            raise HTTPException(status_code=503, detail="ComfyUI server is unreachable")
    # "/prompt" returns prompt ID
    prompt_id = response.json().get("prompt_id")

    # DATABASE INSERT
    new_job = JobRecord(
        job_id=job_id,
        prompt_id=prompt_id,
        status="queued",
        model_name=request.model_name.value,
        query=request.query,
        seed=seed_val
    )
    db.add(new_job)
    await db.commit()

    return {
        "job_id": job_id,
        "status": "queued",
        "message": "Image generation started"
    }

@app.get("/api/portfolio/status/{job_id}")
    # The frontend polls this endpoint to check if the image is ready.
async def check_status(job_id: str, db: AsyncSession = Depends(get_db)):
    # DATABASE SELECT
    result = await db.execute(select(JobRecord).where(JobRecord.job_id == job_id))
    job = result.scalars().first()

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # If it's already completed in the DB, just return it without pinging ComfyUI
    if job.status == "completed":
        return {
            "job_id": job.job_id,
            "status": "completed",
            "download_url": job.image_url
        }

    async with httpx.AsyncClient(timeout=5.0) as client:
        # Query "/history{prompt_id}"
        history_rest = await client.get(f"{COMFY_API_URL}/history/{job.prompt_id}")
        in_history = history_rest.json().get(job.prompt_id, {})

        # If the prompt_id query returns from "/history" then imagegen is complete, retrieve.
        if in_history:

            # 1. Check if ComfyUI explicitly reported a node failure
            if in_history.get("status", {}).get("status_str") == "error":
                job.status = "failed"
                await db.commit()
                return {"job_id": job_id, "status": "failed", "detail": "ComfyUI threw an internal error."}

            # 2. Bypass the missing outputs dictionary entirely!
            # Because we forced ComfyUI to use our unique job_id as the prefix,
            # it will ALWAYS append _00001_.png to the first generation.
            img_info = {
                "filename": f"{job_id}_00001_.png",
                "subfolder": "",
                "type": "output"
            }

            # Once img_info is filled, return URL where frontend can download image
            if img_info:
                # DATABASE UPDATE
                job.status = "completed"
                job.image_url = f"/api/portfolio/image/{job_id}"
                job.image_info = img_info

                await db.commit()

                return {
                    "job_id": job_id,
                    "status": "completed",
                    "download_url": job.image_url
                }
            else:
                job.status = "failed"
                await db.commit()
                return {"job_id": job_id, "status": "failed", "detail": "No image output found."}

        # If it's not in the history yet, it's still queued or executing
        return {"job_id": job_id, "status": "processing"}

@app.get("/api/portfolio/image/{job_id}")
async def get_image(job_id: str, db: AsyncSession = Depends(get_db)):
    """Serves the generated image securely via database record."""
    #retrieve image_info
    result = await db.execute(select(JobRecord).where(JobRecord.job_id == job_id))
    job = result.scalars().first()

    if not job or not job.image_info:
        raise HTTPException(status_code=404, detail=f"Image not found or not ready for {job_id}")

    img_info = job.image_info

    params = {"filename": img_info["filename"]}

    # Only add subfolder and type if ComfyUI actually provided them as non-empty strings
    if img_info.get("subfolder"):
        params["subfolder"] = img_info["subfolder"]
    if img_info.get("type"):
        params["type"] = img_info["type"]

    async with httpx.AsyncClient(timeout=10.0) as client:
        # Pass all the exact parameters back to ComfyUI so it never gets confused
        img_res = await client.get(
            f"{COMFY_API_URL}/view",
               params=params
        )
        if img_res.status_code != 200:
            raise HTTPException(status_code=404, detail="Image not found on server.")

        return Response(content=img_res.content, media_type="image/png")

@app.get("/api/portfolio/history")
async def get_history(db: AsyncSession = Depends(get_db)):
    """Returns all completed jobs for the React UI gallery, sorted newest first."""
    # Order by created_at descending
    result = await db.execute(
        select(JobRecord)
        .where(JobRecord.status == "completed")
        .order_by(JobRecord.created_at.desc())
    )
    jobs = result.scalars().all()

    return [
        {
            "job_id": job.job_id,
            "query": job.query,
            "seed": job.seed,
            "image_url": job.image_url,
            "created_at": job.created_at
        }
        for job in jobs
    ]

@app.get("/")
async def root():
    return {"message": "Hello World"}


@app.get("/hello/{name}")
async def say_hello(name: str):
    return {"message": f"Hello {name}"}