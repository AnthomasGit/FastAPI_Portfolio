import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routers import projects, scenes, characters, locations, props, ai, generate


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


@app.get("/")
async def root():
    return {"message": "Storyboard Pro API"}
