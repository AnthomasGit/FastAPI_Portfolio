# 3D Scene Staging Pipeline — Low-Level Design & SDLC Plan

**Project:** Storyboard Pro · **Feature:** On-demand 3D scene staging → controlled image → video
**Constraints confirmed:** single 24 GB GPU (3090/4090 class), dev data disposable (schema wipe OK), solo developer, aggressive few-week timeline.
**Codebase reviewed:** `backend/` (FastAPI async, SQLAlchemy, ComfyUI job/poll pattern in `services/comfyui_service.py` + `routers/generate.py`), `portfolio-ui/` (React 19, zustand, react-query, shadcn), `docker-compose.yml` / K3s mounts.

---

## 0. Pre-flight issues found in the codebase (fix before anything else)

1. **Committed secret.** `docker-compose.yml` contains a live OpenRouter API key. Rotate it, move it to a gitignored `.env`, and reference it via `env_file:`. It is in git history — treat it as burned.
2. **No migration tooling.** Schema comes from `Base.metadata.create_all()` at startup. `create_all` never *alters* existing tables, so any column change silently does nothing against an existing DB. Since dev data is disposable, adopt **Alembic now** (it's ~2 hours) and make this feature's schema the first migration. Doing it later, with real data, is much more painful. Keep `init_db()` for tests only.
3. **`--highvram` in ComfyUI CLI args.** This pins models in VRAM. That's fine when you run one workflow family; it will thrash or OOM once you rotate between SDXL/Flux, image-to-3D, rigging, ControlNet+IP-Adapter, and video models on 24 GB. Switch to default VRAM management (see §11).
4. **Model verification.** TRELLIS.2, Hunyuan3D 2.1, UniRig, Wan 2.2, and LTX-Video all move fast (new checkpoints, renamed ComfyUI node packs). Before Milestone 2, verify the exact node pack + checkpoint versions currently maintained — pin them in a custom ComfyUI image (§11), don't install at container start.

---

# Part 1 — Low-Level Design

## 1. Architecture at a glance

No new services. Everything below is: new SQLAlchemy models in `database.py` (or a split `models/` package), new routers, new service modules, new workflow JSONs, and one substantial new frontend route (the R3F stage editor). The existing pattern — service builds workflow JSON → `POST {COMFY_API_URL}/prompt` → store `job_id`/`prompt_id` → frontend polls a status endpoint — is reused for all four new GPU job types (mesh, rig, controlled image, video).

Two file-flow facts from your compose file that the design leans on:

- The backend container already mounts `/opt/ComfyUI/input`. So the backend can **write files directly into ComfyUI's input directory** (uploaded reference photos, rembg output, client-rendered depth maps) and reference them by filename in `LoadImage` nodes. No new storage service needed.
- ComfyUI's output directory is served via `GET /view`, which you already proxy for images. GLB meshes and MP4s come back the same way (`SaveGLB` / video save nodes write to output; backend proxies with the right `media_type`).

Object storage (S3/MinIO) is deliberately deferred — local volumes are fine at this scale and the URL fields in the schema are storage-agnostic strings, so swapping later is a service-layer change, not a schema change.

```
React (R3F editor) ──REST──► FastAPI monolith ──HTTP──► ComfyUI (:8188, 1 GPU, FIFO queue)
        │                        │      │
        │  polls status          │      └── writes uploads/depth maps → /opt/ComfyUI/input
        └────────────────────────┘      └── proxies outputs (PNG/GLB/MP4) ◄── /opt/ComfyUI/output
                              PostgreSQL 15
```

## 2. Database schema

### 2.1 Design decisions

- **Polymorphic `Reference`** uses `entity_type` + `entity_id` + `role`, as you specified. Trade-off to be aware of: `entity_id` cannot be a real foreign key (it points at four different tables), so DB-level cascade delete is lost for references. Mitigation: app-level cascade in the delete endpoints for Character/Prop/Location/Scene (one shared helper), plus a composite index on `(entity_type, entity_id)`.
- **`Character.reference_url` is dropped**, not kept alongside. Two sources of truth for "the character's reference image" is a bug farm. Backward compatibility is preserved with zero frontend changes by *deriving* `reference_url` in `CharacterResponse` from the reference with `role='primary'` (a `@computed_field` / resolver in the schema). The existing storyboard cells keep working.
- **`JobRecord` is promoted** from underused to the single generic GPU-job ledger. Every GPU job (mesh, rig, controlled image, video) writes one row with a `job_type`. Domain tables (`Asset3D`, `GeneratedImage`, `GeneratedVideo`) keep their own `status` for fast reads, but `JobRecord` gives you one place to build a job-history/debug view and one polling code path.
- **Immutable artifacts, mutable staging.** `SceneStaging` is the only mutable record (the editor autosaves it). `SceneCapture`, `GeneratedImage`, `GeneratedVideo`, `Asset3D` are append-only: a retry creates a *new* row rather than mutating history. This is what makes "every stage independently inspectable and retryable" cheap — the UI is just listing rows. `SceneCapture` additionally freezes a `staging_snapshot` JSON, because the staging will keep changing after capture and you need to know what the depth map actually depicted.
- **One staging per scene** (`UNIQUE(scene_id)`), matching "a `SceneStaging` record per Scene". Versioned stagings are deliberately out of scope.

### 2.2 SQLAlchemy models (matching existing conventions)

```python
# --- Reference: replaces the scene-only version. Drop old table in the migration. ---

class Reference(Base):
    __tablename__ = "references"
    __table_args__ = (
        Index("ix_references_entity", "entity_type", "entity_id"),
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    entity_type = Column(String, nullable=False)   # 'scene' | 'character' | 'location' | 'prop'
    entity_id = Column(String, nullable=False)      # no FK — polymorphic; app-level cascade
    role = Column(String, nullable=False, default="moodboard")
    # roles: 'primary' | 'moodboard' | 'turnaround_front' | 'turnaround_side'
    #        | 'turnaround_back' | 'texture_ref' | 'backdrop' | 'tpose'
    url = Column(String, nullable=True)             # filename in ComfyUI input dir, or external URL
    processed_url = Column(String, nullable=True)   # rembg output filename (bg removed), if produced
    description = Column(Text, nullable=True)
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

# Scene keeps a working relationship without a FK, via primaryjoin:
# on Scene:
#   references = relationship(
#       "Reference",
#       primaryjoin="and_(foreign(Reference.entity_id)==Scene.id, "
#                   "Reference.entity_type=='scene')",
#       viewonly=False, cascade="all, delete-orphan",
#   )
# Character/Location/Prop get the same pattern with their entity_type.


# --- Asset3D: one row per mesh-generation attempt for a Character or Prop ---

class Asset3D(Base):
    __tablename__ = "assets_3d"
    __table_args__ = (Index("ix_assets3d_entity", "entity_type", "entity_id"),)

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    entity_type = Column(String, nullable=False)          # 'character' | 'prop'  (never 'location')
    entity_id = Column(String, nullable=False)
    source_reference_id = Column(String, ForeignKey("references.id", ondelete="SET NULL"), nullable=True)

    status = Column(String, default="queued")
    # queued | mesh_processing | mesh_ready | rig_queued | rig_processing
    # | rigged | mesh_failed | rig_failed        (props terminate at mesh_ready)

    mesh_url = Column(String, nullable=True)              # GLB filename in ComfyUI output
    rigged_mesh_url = Column(String, nullable=True)       # rigged GLB filename
    preview_url = Column(String, nullable=True)           # optional turntable/thumbnail render

    mesh_job_id = Column(String, nullable=True)           # FKs into jobs.job_id conceptually
    rig_job_id = Column(String, nullable=True)
    params = Column(JSON, nullable=True)                  # {model: 'hunyuan3d-2.1', seed, ...}
    error = Column(Text, nullable=True)                   # last failure message (user-visible)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# --- SceneStaging: the mutable editor document, one per scene ---

class SceneStaging(Base):
    __tablename__ = "scene_stagings"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    scene_id = Column(String, ForeignKey("scenes.id", ondelete="CASCADE"),
                      nullable=False, unique=True)
    backdrop_reference_id = Column(String, ForeignKey("references.id", ondelete="SET NULL"),
                                   nullable=True)   # a Location reference with role='backdrop'
    camera = Column(JSON, nullable=True)
    # {position:[x,y,z], target:[x,y,z], fov: float, aspect: float}
    blockout = Column(JSON, nullable=True)
    # [{id, kind:'floor'|'box'|'plane', transform:{pos,rot,scale}, label?}]
    placements = Column(JSON, nullable=True)
    # [{id, asset3d_id, transform:{pos,rot,scale}, pose:{boneName:[qx,qy,qz,qw], ...}|null}]
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    scene = relationship("Scene", back_populates="staging")
    captures = relationship("SceneCapture", back_populates="staging",
                            cascade="all, delete-orphan")


# --- SceneCapture: immutable snapshot of a chosen shot ---

class SceneCapture(Base):
    __tablename__ = "scene_captures"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    staging_id = Column(String, ForeignKey("scene_stagings.id", ondelete="CASCADE"), nullable=False)
    camera = Column(JSON, nullable=False)                # frozen camera params at capture time
    staging_snapshot = Column(JSON, nullable=False)      # frozen blockout+placements+backdrop
    depth_map_url = Column(String, nullable=False)       # PNG filename in ComfyUI *input* dir
    edge_map_url = Column(String, nullable=True)         # optional lineart/canny render
    width = Column(Integer, nullable=False)
    height = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    staging = relationship("SceneStaging", back_populates="captures")
    generated_images = relationship("GeneratedImage", back_populates="capture")


# --- GeneratedImage: extended ---
# add to existing model:
#   capture_id = Column(String, ForeignKey("scene_captures.id", ondelete="SET NULL"), nullable=True)
#   kind = Column(String, default="txt2img")   # 'txt2img' | 'controlled'
#   params = Column(JSON, nullable=True)       # {controlnet_strength, ip_adapter_weight, seed, ...}
#   error = Column(Text, nullable=True)
#   capture = relationship("SceneCapture", back_populates="generated_images")


# --- GeneratedVideo: new, mirrors GeneratedImage ---

class GeneratedVideo(Base):
    __tablename__ = "generated_videos"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String, ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)
    scene_id = Column(String, ForeignKey("scenes.id", ondelete="SET NULL"), nullable=True)
    source_image_id = Column(String, ForeignKey("generated_images.id", ondelete="SET NULL"), nullable=True)
    prompt = Column(Text, nullable=True)                 # motion prompt
    video_url = Column(String, nullable=True)            # MP4/WebM filename in ComfyUI output
    status = Column(String, default="queued")            # queued|processing|completed|failed
    job_id = Column(String, nullable=True)
    prompt_id = Column(String, nullable=True)
    params = Column(JSON, nullable=True)                 # {model:'ltx-video', frames, fps, seed}
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


# --- JobRecord: extended into the generic GPU-job ledger ---
# add to existing model:
#   job_type = Column(String, nullable=False, default="image")
#       # 'image' | 'controlled_image' | 'mesh' | 'rig' | 'video'
#   entity_type = Column(String, nullable=True)   # what domain row this job belongs to
#   entity_id = Column(String, nullable=True)     # e.g. ('asset3d', <id>), ('generated_video', <id>)
#   error = Column(Text, nullable=True)
#   finished_at = Column(DateTime, nullable=True)
```

**Migration note:** one Alembic revision: drop old `references`, create the tables above, alter `generated_images` and `jobs`. Since data is disposable, no data migration script is needed — but write the revision properly anyway so the habit exists before real data does.

## 3. API specification

Conventions matched to the codebase: `/api/...` paths, `APIRouter()` per resource file, `Depends(get_db)`, Pydantic response models with `from_attributes`, 404 via `HTTPException`, trigger endpoints return `{*_id}` and the frontend polls a status endpoint.

### 3.1 Uploads & references — `routers/references.py`

| Method | Path | Body / Params | Returns | Notes |
|---|---|---|---|---|
| POST | `/api/uploads` | multipart `file` | `{url}` | Validates image (Pillow), writes UUID-named file to ComfyUI input mount. Shared by reference photos and depth maps. |
| GET | `/api/{entity_type}/{entity_id}/references` | `entity_type ∈ scenes\|characters\|locations\|props` | `List[ReferenceResponse]` | Path enum validated. |
| POST | `/api/{entity_type}/{entity_id}/references` | `ReferenceCreate {url, role, description}` | `ReferenceResponse` (201) | 404 if entity missing. |
| PUT | `/api/references/{id}` | `ReferenceUpdate {role?, description?, sort_order?}` | `ReferenceResponse` | |
| DELETE | `/api/references/{id}` | — | 204 | |
| POST | `/api/references/{id}/remove-background` | — | `ReferenceResponse` | Runs rembg **in the backend process** (CPU, `rembg` lib — no GPU job, no queue), writes `processed_url`. Synchronous is fine (~1–3 s); if it proves slow, move to `BackgroundTasks`. |

### 3.2 3D assets — `routers/assets3d.py`

| Method | Path | Body | Returns | Notes |
|---|---|---|---|---|
| POST | `/api/assets3d/generate` | `{entity_type, entity_id, reference_id, params?}` | `{asset3d_id}` (202) | Rejects `entity_type='location'` with 422 (architectural rule enforced server-side). Auto-runs rembg on the reference if `processed_url` is missing. Queues mesh workflow. |
| GET | `/api/assets3d/{id}` | — | `Asset3DResponse` | Polling endpoint — also advances status from ComfyUI history, same pattern as `poll_generation_status`. |
| GET | `/api/projects/{project_id}/assets3d` | — | `List[Asset3DResponse]` | For the editor's asset drawer. |
| POST | `/api/assets3d/{id}/rig` | — | `{asset3d_id}` (202) | 409 unless status is `mesh_ready` or `rig_failed`. Characters only (422 for props). |
| POST | `/api/assets3d/{id}/retry` | — | `{asset3d_id}` (202) | Retries whichever stage failed (`mesh_failed`→mesh, `rig_failed`→rig). Mesh retry gets a new seed by default. |
| GET | `/api/assets3d/{id}/mesh?rigged=bool` | — | binary GLB | Proxies ComfyUI `/view`, `media_type="model/gltf-binary"`. |
| DELETE | `/api/assets3d/{id}` | — | 204 | Blocked (409) if referenced by any staging placement. |

### 3.3 Staging & capture — `routers/staging.py`

| Method | Path | Body | Returns | Notes |
|---|---|---|---|---|
| GET | `/api/scenes/{scene_id}/staging` | — | `SceneStagingResponse` | Creates an empty staging on first GET (upsert-on-read) so the editor never handles a 404. |
| PUT | `/api/scenes/{scene_id}/staging` | `SceneStagingUpdate {camera?, blockout?, placements?, backdrop_reference_id?}` | `SceneStagingResponse` | Editor autosaves (debounced ~2 s). Validates every `asset3d_id` in placements exists and belongs to the project. |
| POST | `/api/scenes/{scene_id}/staging/captures` | multipart: `depth_map` (PNG), `edge_map?`, `camera` (JSON str), `width`, `height` | `SceneCaptureResponse` (201) | Depth/edge maps are **rendered client-side by Three.js** and uploaded; backend stores them in the ComfyUI input dir and freezes `staging_snapshot` from the current staging row. |
| GET | `/api/scenes/{scene_id}/staging/captures` | — | `List[SceneCaptureResponse]` | Capture history for the inspect UI. |
| GET | `/api/captures/{id}/depth` | — | PNG | Proxy for inspection ("show the depth map" requirement). |
| DELETE | `/api/captures/{id}` | — | 204 | |

### 3.4 Controlled generation & video — extend `routers/generate.py` + new `routers/video.py`

| Method | Path | Body | Returns | Notes |
|---|---|---|---|---|
| POST | `/api/generate/controlled` | `{capture_id, prompt_override?, params?}` | `{generation_id}` (202) | Builds prompt via existing `construct_prompt()` (scene resolved from capture→staging→scene), conditions ControlNet on the capture's depth map and IP-Adapter on the scene's character/prop/location `primary`/`backdrop` references. Creates `GeneratedImage(kind='controlled', capture_id=...)`. |
| GET | `/api/generate/status/{generation_id}` | — | existing | Unchanged — controlled images flow through the same poller. |
| POST | `/api/generate/video` | `{image_id, motion_prompt?, params?}` | `{video_id}` (202) | 409 unless source image status is `completed`. |
| GET | `/api/generate/video/status/{video_id}` | — | `{id, status, video_url?}` | Same poll pattern. |
| GET | `/api/generate/video/file/{video_id}` | — | binary MP4 | Proxies ComfyUI `/view`, `media_type="video/mp4"`. |

`lib/api.js` gets one function per endpoint, same style as existing entries.

## 4. Pipeline state machine

Two coupled machines: **per-asset** (stages 1–3, one instance per Character/Prop) and **per-scene** (stages 4–7). They interact only through a readiness check: a scene's editor can place any asset whose status is `mesh_ready` (props, or unrigged characters) or `rigged` (posable characters).

### 4.1 Asset3D states

```
                    ┌───────────── retry (new seed) ─────────────┐
                    ▼                                            │
 queued ──► mesh_processing ──► mesh_ready ──[prop]──► (terminal ok)
                    │                 │
                    │                 └─[character, user triggers rig]──► rig_queued
                    ▼                                                        │
               mesh_failed                                                   ▼
                                                              rig_processing ──► rigged (terminal ok)
                                                                     │
                                                                     ▼
                                                                rig_failed ──retry──► rig_queued
```

Transition rules:

| From | Event | To | Notes |
|---|---|---|---|
| queued | workflow accepted by ComfyUI (`prompt_id` returned) | mesh_processing | |
| queued / mesh_processing | ComfyUI POST fails / history reports error / poll timeout (30 min) | mesh_failed | `error` populated; retryable |
| mesh_processing | history complete, GLB present | mesh_ready | |
| mesh_ready, rig_failed | user triggers rig (characters only) | rig_queued | rig is **user-triggered, never automatic** — it's the flakiest stage and the user should see the mesh first |
| rig_queued | accepted | rig_processing | |
| rig_processing | complete, rigged GLB present | rigged | |
| rig_processing | error/timeout | rig_failed | mesh remains usable unposed — rig failure is *not* asset failure |
| mesh_failed | retry | queued | new `Asset3D` params seed; same row (pre-artifact failure may mutate in place — nothing downstream references a failed row) |

**Hard failure vs retry:** transport/GPU errors and quality rejections are retryable indefinitely (each retry is a fresh seed). The only *hard* failures are validation errors (bad/missing reference image, unsupported entity type) — those return 4xx at trigger time and never create a job.

### 4.2 Scene-level flow (gating, not a stored status)

Scene stage readiness is **derived**, not stored — storing it invites drift. Gates:

```
edit staging  : allowed always (even with zero assets — blockout/backdrop only)
capture       : requires a staging row (trivially true) — captures are cheap, allow many
controlled gen: requires capture_id; POST /generate/controlled
video         : requires a completed GeneratedImage
```

Regenerating upstream **never invalidates downstream artifacts** — a capture keeps its frozen snapshot; an image keeps pointing at its capture; a video keeps pointing at its image. "Retry" at any scene stage = create a new row from the same upstream input. The UI presents each stage as a list of attempts (inspectable), newest first. The "once, on demand, never parallel across scenes" rule is enforced socially by the UI (single trigger button per stage per scene) plus ComfyUI's inherently serial FIFO queue — no distributed locking needed on one GPU.

## 5. Module & component boundaries

### 5.1 Backend

```
backend/
├── services/
│   ├── comfyui_client.py        # NEW: extracted generic core — load_workflow(name),
│   │                            #   inject(workflow, overrides), submit(workflow) -> prompt_id,
│   │                            #   poll(prompt_id) -> {status, outputs}, view_file(filename)
│   │                            #   (refactor of the generic halves of comfyui_service.py;
│   │                            #    existing generate_scene_image is rewritten on top of it)
│   ├── comfyui_service.py       # existing txt2img/img2img, now thin over comfyui_client
│   ├── preprocess_service.py    # NEW: rembg background removal (CPU, in-process)
│   ├── asset3d_service.py       # NEW: build/submit/poll mesh + rig workflows,
│   │                            #   Asset3D state transitions, JobRecord writes
│   ├── staging_service.py       # NEW: staging upsert/validation, capture creation
│   │                            #   (file persistence + snapshot freeze)
│   ├── controlled_gen_service.py# NEW: ControlNet+IP-Adapter workflow assembly
│   │                            #   (reuses construct_prompt from comfyui_service)
│   └── video_service.py         # NEW: image-to-video workflow build/submit/poll
├── routers/
│   ├── references.py            # NEW  (uploads + polymorphic reference CRUD)
│   ├── assets3d.py              # NEW
│   ├── staging.py               # NEW
│   ├── video.py                 # NEW
│   └── generate.py              # extended: /generate/controlled
├── workflows/
│   ├── mesh_hunyuan3d_21.json   # image → textured GLB
│   ├── rig_unirig.json          # GLB → rigged GLB
│   ├── image_controlnet_ipadapter.json
│   └── video_ltx.json           # (or video_wan22_5b.json — see §11)
└── alembic/                     # NEW: migrations
```

The one refactor worth its cost on this timeline is `comfyui_client.py`: four new job types each needing load/inject/submit/poll would otherwise mean four copies of the same 60 lines. Inject moves from the current heuristic string-matching to **explicit per-workflow node maps** (`{"prompt_node": "6", "image_node": "12", "seed_node": "3"}` stored alongside each workflow JSON) — the heuristic (`"neg" in str(node_data).lower()`) is already fragile and will misfire on complex ControlNet graphs.

### 5.2 Frontend

```
portfolio-ui/src/
├── routes/
│   └── SceneStage.jsx           # NEW route: /project/:id/scene/:sceneId/stage
├── components/stage3d/          # NEW — all R3F lives here, nothing else imports three
│   ├── StageCanvas.jsx          # <Canvas>, lighting, grid, selection plumbing
│   ├── BackdropPlane.jsx        # location photo on a plane, locked to back, scalable
│   ├── BlockoutObject.jsx       # floor/box/plane primitives + TransformControls
│   ├── PlacedAsset.jsx          # GLB via useGLTF from /api/assets3d/:id/mesh
│   ├── PoseControls.jsx         # bone list + rotate gizmo for rigged assets (post-MVP)
│   ├── CameraRig.jsx            # user camera vs. "shot camera" (frustum helper preview)
│   ├── CaptureRenderer.jsx      # offscreen render target: depth pass → PNG blob
│   ├── AssetDrawer.jsx          # project assets w/ status chips, generate/rig/retry buttons
│   ├── PipelinePanel.jsx        # per-stage history: captures, images, videos; inspect+retry
│   └── StageToolbar.jsx
├── stores/
│   └── stagingStore.js          # NEW zustand store (see below)
└── lib/api.js                   # extended
```

New deps: `three`, `@react-three/fiber`, `@react-three/drei` (TransformControls, useGLTF, CameraControls, useFBO).

**State management split** (this matters — mixing them makes the editor miserable):

- **zustand (`stagingStore`)** owns the live editor document: placements, blockout, camera, selection, dirty flag. Transform drags update the store at frame rate; a debounced (~2 s) effect PUTs the staging. This is the same pattern as your existing `projectStore`.
- **react-query** owns all server/async state: asset list + statuses (with `refetchInterval` while any job is non-terminal — replacing hand-rolled polling loops), captures, generations, videos. Trigger endpoints are mutations that invalidate the relevant query.
- GLBs are fetched by `useGLTF` straight from the mesh proxy endpoint and cached by drei; they never enter either store.

**Depth capture implementation note:** render the staged scene to an offscreen FBO at the shot camera with `MeshDepthMaterial` (or a small custom shader writing linearized depth), **excluding the backdrop plane** — a photo-textured plane at constant depth is a lie ControlNet will happily believe (see risk R5). Also render an optional edge pass. `canvas.toBlob()` → multipart POST. Everything stays client-side until the PNG upload, honoring "frontend never talks to the GPU box."

**UI requirement carried from your spec:** the reference-upload UI for characters must state the constraint (front-facing, neutral T/A-pose, uncluttered background) *at upload time*, show the rembg preview before mesh generation, and warn — not block — when the user proceeds anyway.

## 6. Happy-path sequence (full pipeline)

```
── Stage 1: reference ──────────────────────────────────────────────────────
User → POST /api/uploads (photo)                    → {url}
User → POST /api/characters/{id}/references {url, role:'tpose'}
User → POST /api/references/{rid}/remove-background → processed_url set (rembg, in-process)

── Stage 2: mesh ───────────────────────────────────────────────────────────
User → POST /api/assets3d/generate {character, id, rid}
  asset3d_service: create Asset3D(queued) + JobRecord(job_type='mesh')
  comfyui_client: load mesh_hunyuan3d_21.json, inject processed image filename + seed
                  POST comfy /prompt → prompt_id → status=mesh_processing → 202 {asset3d_id}
UI (react-query, 3s interval) → GET /api/assets3d/{id}
  poller: GET comfy /history/{prompt_id} → complete → mesh_url set → mesh_ready
UI renders GLB inline (inspectable) via GET /api/assets3d/{id}/mesh

── Stage 3: rig (characters, user-triggered) ──────────────────────────────
User → POST /api/assets3d/{id}/rig → rig_queued → rig_processing → rigged
  (on failure: rig_failed shown with error; Retry re-queues; asset usable unposed meanwhile)

── Stage 4: staging (no GPU) ───────────────────────────────────────────────
UI  → GET /api/scenes/{sid}/staging            (auto-created empty)
User sets backdrop (location ref), blocks out floor/walls, drags assets, frames camera
UI  → debounced PUT /api/scenes/{sid}/staging  (autosave)

── Stage 5: capture ────────────────────────────────────────────────────────
User clicks Capture
UI  → offscreen depth render (backdrop excluded) → PNG blob
UI  → POST /api/scenes/{sid}/staging/captures (depth_map, camera, dims)
  staging_service: save PNG → ComfyUI input dir; freeze staging_snapshot → 201 {capture}

── Stage 6: controlled image ───────────────────────────────────────────────
User → POST /api/generate/controlled {capture_id}
  controlled_gen_service: prompt = construct_prompt(scene); workflow =
    ControlNet(depth=capture.depth_map) + IP-Adapter(refs: char/prop primary,
    location backdrop) + CLIPTextEncode(prompt)
  → GeneratedImage(kind='controlled', capture_id, processing) → 202
UI polls GET /api/generate/status/{gen_id} → completed → image shown next to its depth map

── Stage 7: video ──────────────────────────────────────────────────────────
User → POST /api/generate/video {image_id, motion_prompt}
  video_service → workflow video_ltx.json(image, prompt) → GeneratedVideo(processing)
UI polls /api/generate/video/status/{vid} → completed → <video src=/api/generate/video/file/{vid}>
```

---
# Part 2 — SDLC Plan

## 7. Scope reality check (read this first)

On an aggressive few-week solo timeline, the full seven-stage pipeline is **not** an MVP — it's three products (a 3D asset generator, a 3D editor, and a controlled-generation pipeline). The honest cut:

**v1 (the MVP that proves the thesis):** polymorphic references + uploads → mesh generation (no rigging) → staging editor (place *unposed* meshes + blockout + backdrop + camera) → depth capture → **ControlNet-depth-only** controlled generation.

That v1 already delivers the core product value: *composition and framing locked from a 3D staging*. Everything else sharpens it:

- **IP-Adapter identity conditioning** — v1.1. It's a tuning problem, not a plumbing problem; land plumbing first with depth-only, then tune.
- **Rigging + posing** — v1.2. Flakiest stage, and unposed "A-pose statues" still stage a shot usefully. Posing UI (per-bone gizmo) is real work; pose *presets* are explicitly deferred (see R6).
- **Video** — v1.3. Fully decoupled (input is just a completed image), so it slots in last with zero rework.

If the timeline compresses further, cut from the bottom of that list upward. Do not cut inspectability/retry — it's load-bearing for everything above it.

## 8. Milestones with exit criteria

**M0 — Foundations (short)**
Rotate the leaked key → `.env`. Add Alembic; initial revision = current schema. Extract `comfyui_client.py`; existing image generation still green. Add `pytest` + `pytest-asyncio` + `respx`, first tests around the client.
*Exit:* existing app works unchanged; `alembic upgrade head` from empty DB; CI-runnable test suite exists.

**M1 — References & uploads**
Polymorphic `Reference` migration (drop old table), app-level cascade helper, upload endpoint, rembg endpoint, reference CRUD, `CharacterResponse.reference_url` derived from `role='primary'`. Minimal reference-manager UI on character/prop/location panels with the T-pose guidance copy.
*Exit:* upload → tag role → rembg preview works end-to-end; existing storyboard UI unchanged; cascade delete covered by tests.

**M2 — Mesh pipeline (first new GPU job)**
Pin ComfyUI custom-node image with Hunyuan3D 2.1 (TRELLIS as fallback — decide by running both on 5 test photos, pick the one with better single-photo robustness on your GPU). `mesh_hunyuan3d_21.json` + node map, `asset3d_service`, assets3d router, GLB proxy. AssetDrawer UI with status chips + retry. Golden-set eval v0 (§9).
*Exit:* photo → GLB in UI; failure shows error + Retry works; VRAM measured and logged for the mesh workflow (feeds §11 budget).

**M3 — Staging editor + capture**
R3F canvas, backdrop plane, blockout primitives with TransformControls, GLB placement, dual camera rig, zustand store + debounced autosave, depth-pass capture (backdrop excluded) + upload, capture history panel with depth-map inspection.
*Exit:* a scene can be staged and captured; reload restores staging exactly; depth PNG visually sane (near=bright/far=dark, correct resolution) in the inspect panel.

**M4 — Controlled generation (MVP complete)**
`image_controlnet_ipadapter.json` (depth ControlNet only at first), `/generate/controlled`, PipelinePanel showing capture → image lineage side-by-side. Spike risk R5 *first* (one day: does a blockout depth map steer SDXL usefully? If not, adjust capture rendering before building more).
*Exit (= MVP exit):* stage → capture → generate produces an image whose composition visibly follows the depth map, with per-stage retry and inspection throughout.

**M5 — Identity conditioning (IP-Adapter)**
Add IP-Adapter conditioning on character/prop/location references; expose `controlnet_strength` / `ip_adapter_weight` in `params` and as UI sliders (tuning knobs are a feature, not debug). Extend golden set with identity checks.
*Exit:* same capture, with vs. without reference conditioning, shows measurably better identity (CLIP-similarity delta on the golden set + your eyeballs).

**M6 — Rigging & posing**
`rig_unirig.json`, rig trigger/retry, `rigged` GLB path, PoseControls (bone list + rotate gizmo), pose stored in placement, **posed depth capture** (skinned mesh must be posed in the depth pass).
*Exit:* one character rigged, posed sitting, captured, generated — and a rig failure on a deliberately bad mesh shows `rig_failed` + retry without breaking the asset.

**M7 — Video**
`video_ltx.json` (or Wan 2.2 5B — pick by a VRAM/quality bake-off on 3 images), video service/router/player, generation-time expectations in UI (this stage is minutes, not seconds).
*Exit:* completed image → short clip plays in the PipelinePanel; a failed video job is retryable.

**M8 — Hardening (only if time remains)**
Poll-timeout sweeper for zombie jobs, job-history debug view over `JobRecord`, K3s manifest updates + model-volume docs, load-test the queue with mixed job types.

## 9. Testing strategy for a pipeline full of fallible AI stages

Layered, because "does the code work" and "is the output good" are different questions:

**1. Deterministic unit tests (fast, CI):** workflow injection against node maps (right node gets prompt/image/seed — snapshot-test the injected JSON); Asset3D state-machine transitions including every illegal one (rig on a prop → 422, rig before mesh_ready → 409); polymorphic cascade delete; staging placement validation; capture snapshot freezing.

**2. Contract tests with mocked ComfyUI (fast, CI):** `respx` mocks of `/prompt` and `/history` covering accept, reject, error-in-history, and never-completes (timeout→failed). This is where retry semantics are actually proven, and it's cheap. Also one fixture test that each committed workflow JSON parses and its node map references existing node IDs — catches the "someone re-exported the workflow and node IDs shifted" failure class for free.

**3. Golden-set quality evals (semi-automated, run on the GPU box, not CI):** a `scripts/eval_pipeline.py` that runs fixed inputs at fixed seeds and scores mechanically:

| Stage | Golden input | Automatable checks (trimesh / OpenCV / CLIP) |
|---|---|---|
| Mesh | 5 character + 5 prop photos (varying difficulty) | GLB loads; vertex count in sane band; bounding-box aspect roughly matches silhouette; texture present; watertight-ish (hole count threshold) |
| Rig | the 5 character meshes | bone count in expected band; % vertices with nonzero skin weights > threshold; root bone near origin; applying a 30° arm rotation moves expected vertices |
| Controlled image | 3 canned captures (depth PNG + prompt) | run MiDaS/DepthAnything on the output, correlate against the conditioning depth (composition adherence score); CLIP image-similarity between output crops and reference photos (identity score, from M5) |
| Video | 2 canned images | decodes; frame count/fps as requested; first frame ≈ input image (SSIM threshold) |

Thresholds start loose and are ratcheted from observed baselines. The point is **regression detection** (a node-pack update quietly degrading output) and honest tracking of stage reliability rates — not absolute quality judgment.

**4. Human review harness:** the PipelinePanel *is* the review tool (inputs and outputs side-by-side per stage). Add a one-click 👍/👎 on generated artifacts writing to `params`; after a few weeks you have real per-stage failure-rate data for free, which feeds directly back into the risk register.

## 10. Risk register

| # | Risk | Likelihood / Impact | Mitigation |
|---|---|---|---|
| R1 | **Auto-rigging unreliability** (UniRig-class riggers fail or produce garbage on non-T-pose / stylized / prop-like meshes) | High / Med | Already structural: rig is user-triggered, optional, retryable, and rig failure ≠ asset failure. Upload-time pose guidance; golden-set rig checks; unposed placement is always a fallback. Deferred to M6 so it can slip without blocking MVP. |
| R2 | **VRAM contention on one 24 GB card** across 5 workflow families (SDXL/Flux, Hunyuan3D, UniRig, ControlNet+IP-Adapter stack, video). Model swap thrash → OOMs or minutes of load time per job. | High / High | Drop `--highvram` (§11); measure per-workflow VRAM in M2/M4/M7 before committing to models; prefer fp8/quantized checkpoints; ComfyUI FIFO already serializes — never add app-side parallelism. If SDXL+ControlNet+IP-Adapter together bust 24 GB, fall back to SD1.5-based ControlNet stack for staging shots. |
| R3 | **Image-to-3D quality variance** from single photos (mangled backs, melted faces, texture smear) | High / Med | rembg preprocessing (in design); strict input guidance in UI; cheap seed-retry; set the product expectation that meshes are *staging proxies*, not hero assets — final pixels come from stage 6, which is exactly why the architecture routes identity through IP-Adapter rather than the mesh. |
| R4 | **ControlNet + IP-Adapter tuning difficulty** — depth strength vs. identity weight vs. prompt is a genuinely fiddly 3-way balance; bad defaults make the whole feature feel broken | Med / High | Split plumbing (M4) from tuning (M5); expose weights as user sliders + persisted `params`; golden-set composition/identity scores make tuning progress measurable instead of vibes; keep a "depth-only" toggle as an escape hatch. |
| R5 | **Depth-map domain gap** — ControlNet depth models are trained on natural depth; a blockout of boxes plus (worst case) a flat backdrop plane produces alien depth signals → warped or over-literal outputs | Med / High | Exclude backdrop from the depth pass (in design); render blockout with soft depth (slight bevel/noise is an option); day-one spike in M4 *before* building on top; if quality is poor at high strength, default to lower ControlNet strength + edge map as secondary conditioning. |
| R6 | **Pose retargeting is unsolved for auto-rigged skeletons** — "standing/sitting/walk presets" assume a canonical skeleton; UniRig outputs vary per mesh, so canned presets won't map | High / Med (scoped) | Presets are explicitly *out* of v1; ship per-bone gizmo posing (works on any skeleton) and store poses as bone-quaternion maps per placement. Presets become feasible later only if you constrain to one rig template. |
| R7 | **Video gen on 24 GB** — Wan 2.2 14B doesn't fit sanely; 5B/LTX-class models fit but with visible quality ceiling and multi-minute runtimes that occupy the whole GPU | Med / Med | Bake-off in M7 (LTX vs Wan 2.2 5B) on real project images; short clips (2–4 s) only; UI sets duration expectations; video is last in build order so it can be cut without touching anything. |
| R8 | **Solo dev + aggressive timeline** — the classic: M3 (editor) silently eats three weeks because 3D UI has infinite polish surface | High / High | Hard MVP line (§7); editor scope fence: TransformControls + drei primitives only, no custom gizmos, no undo/redo in v1, no snapping beyond a ground grid; timebox M3 and cut features, not milestones. |

## 11. Deployment & ops notes (single-GPU K3s)

**Custom ComfyUI image, pinned.** `yanwk/comfyui-boot` + runtime node installs is nondeterministic — a node-pack update will eventually break a workflow on a random redeploy. Build `Dockerfile.comfyui` FROM the boot image, `git clone` each custom node pack at a **pinned commit** (Hunyuan3D/TRELLIS nodes, UniRig wrapper, ControlNet aux, IP-Adapter Plus, video nodes), `pip install` their requirements, bake it. Same image for docker-compose and K3s.

**Model storage.** Everything continues to live under the existing `/opt/ComfyUI/models` hostPath. Budget disk *before* pulling: SDXL/Flux stack you already have (~15–20 GB) + Hunyuan3D 2.1 (~15–25 GB) + ControlNet-depth + IP-Adapter + CLIP-Vision (~10 GB) + UniRig (~5 GB) + LTX/Wan-5B (~15–30 GB) ≈ **60–100 GB new**. Verify free space; add a `models/README.md` manifest (file → source URL → SHA) so the box is reproducible.

**VRAM regime.** Remove `--highvram` from `CLI_ARGS` (compose *and* K3s — they share args by design, keep it that way). Default ComfyUI memory management unloads between dissimilar workflows; you trade ~10–60 s model-load latency per job-type switch for not OOMing. Rough working-set expectations at fp8/fp16 on 24 GB: SDXL+ControlNet+IP-Adapter ~12–16 GB; Hunyuan3D 2.1 ~12–20 GB (texture stage is the peak — if it OOMs, split shape and texture into two chained jobs); LTX/Wan-5B ~14–20 GB. Each fits alone; **no two families fit together** — which is fine, because:

**Queueing.** ComfyUI's internal queue is FIFO and serial — on one GPU that's the correct scheduler and you should not build another one. What the app adds is only: (a) `JobRecord` as the ledger, (b) a periodic sweeper (`asyncio` task in FastAPI lifespan) that marks jobs `failed` after a poll-timeout so a ComfyUI restart can't strand `processing` rows forever, and (c) a queue-depth indicator in the UI (`GET /queue` on ComfyUI) so users understand why their video is behind two mesh jobs. If you ever need priorities or multi-GPU, *that* is the moment a real queue (e.g. arq/Redis) earns its complexity — not now.

**File lifecycle.** ComfyUI's output dir grows unboundedly (images, GLBs, MP4s). Add a weekly cron/K3s CronJob that deletes output files older than N days *that no DB row references* (join against the `*_url` columns). Depth maps in the input dir: same treatment, keyed off `scene_captures`.

**K3s specifics.** ComfyUI stays a single-replica Deployment (or StatefulSet) with the nvidia device plugin resource request — never scale replicas >1 against one GPU. FastAPI deploys as-is; new Python deps: `rembg`, `onnxruntime`, `alembic`, `trimesh` (evals). Run `alembic upgrade head` as an initContainer or a pre-deploy Job rather than at app startup, so a crash-looping migration can't take the API down with it.

---

## Appendix A — Assumptions made (flag if wrong)

1. Single-user, no auth — consistent with the current codebase. Fine for now; becomes the first "real product" gap after this feature.
2. Hunyuan3D 2.1 as primary image-to-3D and LTX-Video as primary video model — both are *defaults to be validated* in M2/M7 bake-offs, not commitments. The workflow-JSON + node-map design makes swapping models a config change.
3. Depth-only ControlNet for MVP, edge map optional — pose (OpenPose-style) conditioning from the 3D skeleton is a natural M6+ extension (render a skeleton pass at capture time) but is not designed in detail here.
4. Reference photos may be external URLs *or* uploads; the mesh pipeline requires uploads (rembg + ComfyUI `LoadImage` need local files), and the UI should steer 3D-bound references to upload.

---

## Appendix B — Add-on: per-entity asset image generation (delta only)

**Concept:** new `AssetImage` = global library of generated entity images. Entities keep their placeholder cells; a generated/chosen image is *assigned* to an entity, which just writes its `role='primary'` Reference — so the derived `reference_url`, the 3D mesh pipeline, and IP-Adapter all pick it up with zero downstream changes.

**Schema (2 changes):**

```python
class AssetImage(Base):
    __tablename__ = "asset_images"
    id, origin_project_id (FK projects, SET NULL)      # drives storage folder only
    entity_type ('character'|'location'|'prop')
    kind ('txt2img'|'img2img')
    source_reference_id (FK references, nullable)       # img2img from a scene-scoped ref
    source_asset_image_id (FK self, nullable)            # img2img from library image → NEW asset in current project ✔
    prompt, image_url, status, job_id, prompt_id, params, error, created_at

# Reference: add asset_image_id = Column(String, ForeignKey("asset_images.id"), nullable=True)
# (provenance; assignment = link, never copy ✔)
```

**Storage/folders:** free via ComfyUI — `filename_prefix = f"assets/{project_id}/{entity_type}s/{job_id}"` creates subfolders in the output dir; the file proxy passes `subfolder` to `/view`. No library UI — flat picker with `project` / `entity_type` filters querying the table.

**Endpoints (routers/asset_images.py):**
- `POST /api/asset-images/generate` `{project_id, entity_type, entity_id?, prompt?, source_reference_id? | source_asset_image_id?}` → 202 `{asset_image_id}`. txt2img reuses `image_z_image_turbo.json`; img2img reuses `image_flux2_klein_image_edit_4b_base.json` (both already in repo — just add node maps). `entity_id` only prefills the prompt from name/description; binding stays explicit.
- `GET /api/asset-images?entity_type=&project_id=` — picker (global, filterable).
- `GET /api/asset-images/{id}/file` — proxy (with subfolder).
- `GET /api/asset-images/{id}` — poll, same pattern.
- `POST /api/{entity_type}/{entity_id}/assign-asset` `{asset_image_id}` — upserts the `primary` Reference (link).

**UI:** entity cell placeholder → "Set image" dialog with three tabs: *Generate (text)* / *Generate (from image: scene reference or library image)* / *Choose existing* (picker grid). Scene-scoped reference uploads are already covered by M1's polymorphic references.

**SDLC impact:** insert as **M1.5** (needs M1 references; must precede M2 since the 3D pipeline consumes the primary reference). Small — reuses `comfyui_client`, existing workflows, existing poll pattern. Exit: entity cell filled via all three paths; img2img from a Project-A library image lands as a new asset foldered under Project B.

**3D-trigger reference selection (fix):** `POST /api/assets3d/generate` makes `reference_id` optional. Server-side default precedence when omitted: `role='tpose'` → any uploaded (non-generated) reference → `primary`. If the resolved reference has `asset_image_id` set (i.e., it's a generated image, not a photo), the response includes a `warning` and the UI shows a "generated image — mesh quality may suffer; pick a T-pose photo?" nudge before queueing. The asset drawer's Generate-3D button opens a reference picker pre-selected to this default.
