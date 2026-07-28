from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db, Project
from schemas.schemas import ClarifyRequest, ClarifyResponse, GenerateStoryboardRequest, StoryboardResponse
from services.ai_service import generate_clarifying_questions, generate_storyboard as ai_generate_storyboard
from services.storyboard_generator import save_storyboard

router = APIRouter()


@router.post("/api/ai/clarify", response_model=ClarifyResponse)
async def clarify_idea(data: ClarifyRequest):
    questions = await generate_clarifying_questions(data.idea)
    return ClarifyResponse(questions=questions)


@router.post("/api/ai/generate-storyboard", response_model=StoryboardResponse)
async def generate_storyboard(data: GenerateStoryboardRequest, db: AsyncSession = Depends(get_db)):
    storyboard = await ai_generate_storyboard(data.idea, data.answers)

    project = Project(idea=data.idea, status="generating")
    db.add(project)
    await db.flush()

    await save_storyboard(db, project.id, storyboard)

    return StoryboardResponse(
        project_id=project.id,
        message="Storyboard generated successfully"
    )
