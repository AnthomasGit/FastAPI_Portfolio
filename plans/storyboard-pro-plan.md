# Storyboard Pro — Implementation Plan

## Overview
AI-powered storyboard app for filmmaking. Replace existing portfolio app. User enters rough idea, AI clarifies via Q&A, generates an editable storyboard with scenes, characters, locations, props. "Run" button sends to ComfyUI for image generation.

## Stack
| Layer | Technology |
|-------|-----------|
| Frontend | React 19 + Vite 8 + Tailwind 4 + shadcn/ui |
| Backend | FastAPI + SQLAlchemy (async) + PostgreSQL |
| Inference | DeepSeek V4 Flash Free via OpenZen (Docker sidecar) |
| Image Gen | ComfyUI (existing) |
| Graph Viz | @xyflow/react |

## Architecture

```
Browser (React :5173)  →  FastAPI (:8000)  →  OpenZen Sidecar (DeepSeek)
                                        →  ComfyUI (:8188)
                                        →  PostgreSQL (:5432)
```

## Project Structure

```
backend/
├── main.py                    # FastAPI app (imports routers)
├── database.py                # Base + engine
├── models/
│   ├── project.py
│   ├── scene.py
│   ├── character.py
│   ├── location.py
│   └── prop.py
├── routers/
│   ├── projects.py
│   ├── scenes.py
│   ├── ai.py
│   └── generate.py
├── services/
│   ├── ai_service.py          # OpenZen client
│   ├── storyboard_generator.py
│   └── comfyui_service.py
├── schemas/
│   └── schemas.py             # Pydantic models
├── requirements.txt
├── pyproject.toml
└── workflows/

portfolio-ui/src/
├── main.jsx                   # BrowserRouter
├── App.jsx                    # Router + Layout
├── routes/
│   ├── Projects.jsx           # / — project list
│   ├── NewProject.jsx         # /new — idea + AI chat
│   ├── Storyboard.jsx         # /project/:id — main board
│   └── Graph.jsx              # /project/:id/graph — ReactFlow
├── components/
│   ├── ui/                    # shadcn/ui
│   ├── storyboard/
│   │   ├── StorySummary.jsx
│   │   ├── SceneTable.jsx
│   │   ├── SceneRow.jsx
│   │   ├── CellScreenplay.jsx
│   │   ├── CellReferences.jsx
│   │   ├── CellCharacters.jsx
│   │   ├── CellLocations.jsx
│   │   ├── CellProps.jsx
│   │   └── CellGeneration.jsx
│   └── project/
│       ├── IdeaInput.jsx
│       └── ClarificationChat.jsx
├── lib/
│   ├── api.js
│   └── utils.js
└── stores/
    └── projectStore.js
```

## Data Model

### Project
- `id` UUID PK
- `title` VARCHAR(255)
- `idea` TEXT — raw user input
- `clarifications` JSONB — Q&A pairs
- `story_summary` TEXT — AI-generated summary
- `status` VARCHAR(50) — draft, clarifying, generating, complete
- `created_at`, `updated_at` TIMESTAMP

### Scene (rows in storyboard)
- `id` UUID PK
- `project_id` FK → Project
- `scene_number` INT
- `slugline` VARCHAR(255)
- `screenplay` TEXT
- `notes` TEXT
- `sort_order` INT

### Character
- `id` UUID PK
- `project_id` FK → Project
- `name` VARCHAR(255)
- `description` TEXT
- `traits` JSONB
- `reference_url` TEXT

### Location
- `id` UUID PK
- `project_id` FK → Project
- `name` VARCHAR(255)
- `description` TEXT
- `shot_notes` TEXT

### Prop
- `id` UUID PK
- `project_id` FK → Project
- `name` VARCHAR(255)
- `description` TEXT

### Reference (per scene image/url reference)
- `id` UUID PK
- `scene_id` FK → Scene
- `url` TEXT
- `description` TEXT
- `type` VARCHAR(50)

### GeneratedImage
- `id` UUID PK
- `scene_id` FK → Scene
- `prompt` TEXT
- `image_url` TEXT
- `status` VARCHAR(50)
- `job_id` VARCHAR(255)

### Join tables: scene_characters, scene_locations, scene_props

## API Routes

```
POST   /api/projects                    # Create from idea
GET    /api/projects                    # List all
GET    /api/projects/:id                # Full project with nested data
PUT    /api/projects/:id                # Update
DELETE /api/projects/:id

POST   /api/ai/clarify                  # Idea → clarifying questions
POST   /api/ai/generate-storyboard      # Idea + answers → full storyboard

GET    /api/projects/:id/scenes         # List scenes
POST   /api/projects/:id/scenes         # Create scene
PUT    /api/scenes/:id                  # Update scene
DELETE /api/scenes/:id
PUT    /api/scenes/reorder              # Reorder scenes

GET/POST/PUT/DELETE for characters, locations, props

POST   /api/generate/scene/:id          # Single scene → ComfyUI
POST   /api/generate/project/:id        # Batch all scenes
GET    /api/generate/status/:job_id     # Poll
GET    /api/generate/image/:id          # Get image

GET    /api/projects/:id/graph          # → nodes + edges for ReactFlow
```

## Data Flow

1. **Idea → Clarification**: POST /api/ai/clarify → DeepSeek returns questions → Chat UI
2. **Answers → Storyboard**: POST /api/ai/generate-storyboard → DeepSeek returns structured JSON → Saved to DB
3. **Inline editing**: PUT endpoints → Optimistic UI (Zustand)
4. **Run**: POST /api/generate/scene/:id → Prompt built from scene data → ComfyUI → Poll → Display
5. **Graph**: GET /api/projects/:id/graph → Nodes (entities) + Edges (relationships) → ReactFlow

## Storyboard UI Layout

```
[Story Summary] — locations, characters, props
[Scene Table] — horizontally scrollable
  | Screenplay | References | Characters | Locations | Props | Video Gen |
  | Scene 1    | [imgs]     | character  | location  | props | [image]   |
  | Scene 2    | [imgs]     | cards      | + shots   |       |           |
  [+ Add Scene]
[▶ RUN ALL SCENES button at bottom]
```

## Implementation Steps

### Phase 1: Foundation
1. Save plan, install deps (shadcn/ui, xyflow, zustand, react-query, react-router-dom, lucide-react)
2. Create SQLAlchemy models + Pydantic schemas
3. Refactor main.py into modular routers
4. Add OpenZen sidecar to docker-compose.yml
5. Create ai_service.py

### Phase 2: AI Integration
6. POST /api/ai/clarify — DeepSeek generates questions
7. POST /api/ai/generate-storyboard — structured JSON generation
8. GET /api/projects/:id/graph — build nodes/edges

### Phase 3: Frontend Pages
9. Project list + new project page with clarification chat
10. Storyboard page with SceneTable, all cell types, inline editing
11. Graph page with ReactFlow

### Phase 4: Generation
12. comfyui_service.py — prompt construction + ComfyUI submission
13. Generation UI per scene + Run All button
14. Integration test + polish
