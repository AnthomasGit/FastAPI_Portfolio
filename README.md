# FastAPI Portfolio

AI image generation portfolio powered by **FastAPI**, **ComfyUI**, and **React**.

Two ComfyUI workflows run on a GPU server via K3s:
- **txt2img** (SDXL Turbo) — generate an image from a text prompt.
- **img2img** (Flux) — edit an uploaded image using a text prompt.

## Architecture

| Layer | Tech | Port |
|---|---|---|
| Frontend | React + Vite + Tailwind v4 | 5173 (dev), 80 (prod) |
| API | FastAPI (Python) | 8000 |
| Engine | ComfyUI headless | 8188 |
| Database | PostgreSQL 15 (async) | 5432 |

The frontend polls the API every 2s until the image is ready. Images are proxied through FastAPI, not served directly from ComfyUI. JIT model warming fires on first input focus.

## Quick start

```bash
# Full local stack (ComfyUI, API, UI)
bash backend/dev_server.sh

# Or use Docker Compose
docker compose up
```
