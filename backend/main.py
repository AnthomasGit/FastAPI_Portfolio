import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from routers import projects, scenes, characters, locations, props, ai, generate, references, asset_images, assets3d, staging, video, shots, driving_videos, reference_audios


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Database migrations assumed applied via alembic.")
    yield


app = FastAPI(title="Storyboard Pro", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(projects.router)
app.include_router(scenes.router)
app.include_router(characters.router)
app.include_router(locations.router)
app.include_router(props.router)
app.include_router(ai.router)
app.include_router(generate.router)
app.include_router(references.router)
app.include_router(asset_images.router)
app.include_router(assets3d.router)
app.include_router(staging.router)
app.include_router(video.router)
app.include_router(shots.router)
app.include_router(driving_videos.router)
app.include_router(reference_audios.router)

# Serve uploaded reference images to the frontend.
# Images are saved into the ComfyUI input dir (shared via docker volume)
# so ComfyUI can also read them. The env var COMFY_INPUT_DIR can override
# the default path for non-Docker / custom setups.
COMFY_INPUT_DIR = os.environ.get("COMFY_INPUT_DIR", "/opt/ComfyUI/input")
if os.path.isdir(COMFY_INPUT_DIR):
    app.mount("/api/uploads/file", StaticFiles(directory=COMFY_INPUT_DIR), name="uploads")


@app.get("/")
async def root():
    return {"message": "Storyboard Pro API"}
