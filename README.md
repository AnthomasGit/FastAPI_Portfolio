<!-- Banner -->
<!-- TODO: Add a screenshot or GIF banner here -->

<p align="center">
  <h1 align="center">Storyboard Pro</h1>
  <p align="center"><strong>From a one-line idea to a fully realized storyboard</strong></p>
  <p align="center">AI-assisted storyboard & creative-media studio — script breakdown, image, video, and 3D generation in one pipeline</p>
</p>

<p align="center">
  <a href="#"><img src="https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white" alt="FastAPI" /></a>
  <a href="#"><img src="https://img.shields.io/badge/React-20232A?style=for-the-badge&logo=react&logoColor=61DAFB" alt="React" /></a>
  <a href="#"><img src="https://img.shields.io/badge/PostgreSQL-4169E1?style=for-the-badge&logo=postgresql&logoColor=white" alt="PostgreSQL" /></a>
  <a href="#"><img src="https://img.shields.io/badge/ComfyUI-1a1a1a?style=for-the-badge&logo=nvidia&logoColor=76B900" alt="ComfyUI" /></a>
  <a href="#"><img src="https://img.shields.io/badge/Docker-2496ED?style=for-the-badge&logo=docker&logoColor=white" alt="Docker" /></a>
  <a href="#"><img src="https://img.shields.io/badge/license-MIT-blue?style=for-the-badge" alt="MIT License" /></a>
  <a href="https://your-demo-url.example"><img src="https://img.shields.io/badge/Live_Demo-cloudflare?style=for-the-badge&logo=cloudflare&logoColor=white&color=111" alt="Live Demo" /></a>
</p>

<p align="center">
  <a href="#-features">Features</a> •
  <a href="#%EF%B8%8F-tech-stack">Tech Stack</a> •
  <a href="#-screens">Screens</a> •
  <a href="#-getting-started">Getting Started</a> •
  <a href="#-architecture">Architecture</a> •
  <a href="#-project-structure">Structure</a>
</p>

---

## ✨ Features

- **🧠 LLM Story Breakdown** — Type a project idea and an LLM (via OpenRouter) expands it into structured scenes, characters, locations, and props
- **🖼️ Multi-Model Image Generation** — Run 12+ ComfyUI workflows (Z-Image Turbo, Flux-2 Klein edit, and more) without touching Python per model
- **🎬 Clip Studio** — Image-to-video, reference-to-video, and SCAIL-2 pose-transfer animation with a driving-video library
- **🧊 3D Staging** — Turn a single image into a Gaussian splat or a textured mesh (TripoSG / Trellis2)
- **🔗 Polymorphic References** — Attach any generated asset to any entity (scene / character / location / prop) via one flexible model
- **⚡ Real-Time UX** — The frontend polls generation jobs and warms models just-in-time on first input focus
- **🔒 Proxied Media** — All output is served through the API, never exposed directly from the GPU engine
- **🔁 Swap Models via JSON** — Each workflow ships as a graph + `*.map.json` node map; add a model with two files, not code
- **🌙 Modern Dark UI** — Built with React, Vite, and Tailwind v4

---

## 🛠️ Tech Stack

| Technology | Purpose |
|---|---|
| [FastAPI](https://fastapi.tiangolo.com/) | Async Python API and orchestration layer |
| [SQLAlchemy (async)](https://docs.sqlalchemy.org/) | ORM over PostgreSQL with Alembic migrations |
| [PostgreSQL](https://www.postgresql.org/) | Persistent storage for projects and assets |
| [ComfyUI](https://github.com/comfyanonymous/ComfyUI) | Headless GPU engine for image / video / 3D generation |
| [OpenRouter](https://openrouter.ai/) | OpenAI-compatible LLM for story breakdown |
| [React + Vite](https://vitejs.dev/) | Frontend SPA with file-based routes |
| [Tailwind CSS v4](https://tailwindcss.com/) | Styling and design system |
| [Docker + K3s](https://k3s.io/) | Containerized deploy on a home Kubernetes cluster |

---

## 📱 Screens

<!-- TODO: Add screenshots under docs/screenshots/ and link them in the descriptions -->

| Screen | Description |
|---|---|
| **Projects** | Create and browse storyboard projects |
| **New Project** | Enter a one-line idea; the LLM generates the full scene/character/location/prop breakdown |
| **Storyboard** | Scene-by-scene board with generated images and per-entity references |
| **Scene Detail** | Deep-dive on a single scene with its characters, locations, props, and reference assets |
| **Clip Studio** | Image-to-video, reference-to-video, and pose-transfer animation workspace |
| **Scene Stage / 3D** | Stage a scene and generate 3D assets (Gaussian splat / textured mesh) |
| **Graph** | Visual overview of project entities and their relationships |

---

## 🚀 Getting Started

### Prerequisites

- Python ≥ 3.11 and Node.js ≥ 18
- A running [ComfyUI](https://github.com/comfyanonymous/ComfyUI) instance (GPU recommended)
- PostgreSQL 15 (or use the provided Docker Compose)
- An OpenRouter API key

### Setup

```bash
# Clone the repository
git clone https://github.com/<your-username>/storyboard-pro.git
cd storyboard-pro

# Create environment file
cp .env.example .env   # TODO: add OPENAI_API_KEY, DATABASE_URL, COMFY_* vars
```

```bash
# Full local stack (ComfyUI + API + UI)
bash backend/dev_server.sh

# Or with Docker Compose
docker compose up
```

The API serves on `:8000` and the Vite dev server on `:5173`.

### Testing

Backend tests run against in-memory SQLite with mocked GPU calls — no Postgres or live ComfyUI required:

```bash
cd backend && pytest
```

---

## 🏗️ Architecture

| Layer | Tech | Port |
|---|---|---|
| Frontend | React + Vite + Tailwind v4 | 5173 (dev) / 80 (prod) |
| API | FastAPI (async Python) | 8000 |
| Engine | ComfyUI (headless, GPU) | 8188 |
| Database | PostgreSQL 15 (async SQLAlchemy) | 5432 |
| Deploy | Docker Compose · K3s · Cloudflare Tunnel | — |

**Key engineering decisions**

- **Async everywhere** — FastAPI + async SQLAlchemy + `httpx` keep long-running generation jobs from blocking the API
- **Data-driven workflows** — a `*.map.json` node map indirects prompt/seed/image injection, so ComfyUI graphs swap without code changes
- **Polymorphic references** — one `Reference` model attaches assets to any entity type via a type-tagged relationship
- **GPU-friendly serving** — a shared input volume lets ComfyUI read uploads off disk; output is proxied through FastAPI

> **The frontend never talks to ComfyUI directly** — all generation and media access is mediated by the API for access control and caching.

---

## 📁 Project Structure

```
storyboard-pro/
├── backend/                # FastAPI application
│   ├── routers/            # API route modules (projects, scenes, generate, video, staging, ...)
│   ├── workflows/          # ComfyUI graphs + *.map.json node maps
│   ├── database.py         # Async engine, ORM models, association tables (single source of truth)
│   ├── ai_service.py       # LLM orchestration (OpenRouter)
│   └── dev_server.sh       # Full native dev stack launcher
├── portfolio-ui/           # React + Vite frontend
│   └── src/
│       ├── routes/         # Projects, Storyboard, ClipStudio, SceneDetail, ...
│       ├── components/     # clip / project / scene / stage3d / storyboard / ui
│       └── lib/api.js      # Flat client wrapping every backend endpoint
├── docs/screenshots/       # README screenshots (add your own)
├── docker-compose.yml
└── portfolio.yaml          # K3s deployment manifest
```

---

## 🤝 Contributing

Contributions are welcome! If you have ideas for improvements, new features, or bug fixes:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-idea`)
3. Commit your changes (`git commit -m 'Add amazing idea'`)
4. Push to the branch (`git push origin feature/amazing-idea`)
5. Open a Pull Request

---

## 📄 License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.

---

<p align="center">
  Built with ❤️ by <a href="https://github.com/your-username">Your Name</a>
  <br />
  <!-- TODO: your tagline / role -->
</p>

---
