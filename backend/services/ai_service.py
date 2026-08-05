import os
import re
import json
import ast
import logging
from openai import AsyncOpenAI

logger = logging.getLogger("ai_service")

OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://openrouter.ai/api/v1")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
LLM_MODEL = os.environ.get("LLM_MODEL", "openrouter/free")

client = AsyncOpenAI(
    api_key=OPENAI_API_KEY,
    base_url=OPENAI_BASE_URL,
    timeout=300.0,
    max_retries=0,
)


def extract_json(text: str):
    text = text.strip()
    logger.info("Raw response (first 1500 chars): %s", text[:1500])

    m = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if m:
        text = m.group(1).strip()

    start = text.find("{")
    if start == -1:
        raise ValueError("No JSON object found in response")
    depth = 0
    end = -1
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end == -1:
        raise ValueError("Unmatched braces in response")
    text = text[start:end]

    text = re.sub(r",\s*([}\]])", r"\1", text)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Repair single-quoted JSON (common with weaker models)
    text = re.sub(r"'([^']+?)'(?=\s*:)", r'"\1"', text)
    text = re.sub(r"(?<=:\s*)'([^']*?)'(?=\s*[,}\]])", r'"\1"', text)
    text = re.sub(r"(?<=\[)\s*'([^']*?)'\s*(?=[,\]])", r'"\1"', text)

    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        logger.warning("First repair failed at %s", e)

    # Fallback: ast.literal_eval handles Python-style dicts with single quotes
    try:
        cleaned = text.replace("null", "None").replace("true", "True").replace("false", "False")
        result = ast.literal_eval(cleaned)
        if isinstance(result, dict):
            return result
    except (ValueError, SyntaxError) as e:
        logger.warning("ast.literal_eval fallback failed: %s", e)

    raise json.JSONDecodeError("Failed to parse JSON response", text, 0)


async def generate_clarifying_questions(idea: str) -> list[str]:
    system_prompt = """You are a storyboard development assistant. Given a rough video idea, generate 5-8 clarifying questions that help flesh out the story.
Questions should cover: genre/tone, protagonist, setting/location, conflict, visual style, key scenes, and duration.
Return ONLY valid JSON with a single key "questions" containing an array of strings."""

    response = await client.chat.completions.create(
        model=LLM_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Video idea: {idea}"}
        ],
        temperature=0.7,
        response_format={"type": "json_object"},
        extra_headers={
            "HTTP-Referer": "https://storyboardpro.local",
            "X-Title": "Storyboard Pro",
        },
    )
    data = extract_json(response.choices[0].message.content)
    return data.get("questions", [])


async def generate_storyboard(idea: str, answers: dict) -> dict:
    system_prompt = """You are a professional storyboard developer. Given a film idea and answers to clarifying questions, generate a complete storyboard.

Return a valid JSON object with keys: title, story_summary, scenes.
Each scene has: scene_number, slugline, screenplay.
Each scene also has arrays: characters (objects with name, description), locations (objects with name, description), props (objects with name, description).
Generate 3-6 scenes. Pure JSON only, no markdown."""

    answers_text = "\n".join([f"{q}: {a}" for q, a in answers.items()])

    response = await client.chat.completions.create(
        model=LLM_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Idea: {idea}\n\nAnswers:\n{answers_text}"}
        ],
        temperature=0.7,
        response_format={"type": "json_object"},
        extra_headers={
            "HTTP-Referer": "https://storyboardpro.local",
            "X-Title": "Storyboard Pro",
        },
    )
    return extract_json(response.choices[0].message.content)


async def generate_shot_list(slugline: str, screenplay: str) -> list[dict]:
    """Draft a master shot list for one scene from its screenplay.

    Fills coverage metadata only — never a still/clip, that's the user's job.
    Fields map 1:1 onto the Shot model and later compose into the video motion
    prompt, so the vocabulary is constrained to standard film terms.
    """
    system_prompt = """You are a cinematographer planning coverage for a single film scene.
Given the scene's slugline and screenplay, produce a master shot list that fully covers the action.

Return ONLY valid JSON with a single key "shots" containing an array of 4-8 objects.
Each shot object has these keys (all strings):
- shot_number: sequential like "1A", "1B", "1C" (letter increments per shot)
- shot_size: one of "WS", "MS", "MCU", "CU", "ECU", "POV", "OTS", "Two-Shot"
- angle: one of "High", "Eye-Level", "Low", "Dutch", "Overhead"
- movement: one of "Static", "Pan", "Tilt", "Tracking", "Dolly", "Handheld", "Crane", "Zoom"
- description: one concise sentence describing what this shot shows
- equipment: e.g. "Tripod", "Gimbal", "Handheld", "Dolly track", "Crane"
- audio_notes: diegetic sound/dialogue/ambience for this shot

Cover the scene with a mix of wide establishing, medium, and close-up shots. Pure JSON only, no markdown."""

    response = await client.chat.completions.create(
        model=LLM_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Slugline: {slugline or '(none)'}\n\nScreenplay:\n{screenplay or '(none)'}"}
        ],
        temperature=0.7,
        response_format={"type": "json_object"},
        extra_headers={
            "HTTP-Referer": "https://storyboardpro.local",
            "X-Title": "Storyboard Pro",
        },
    )
    data = extract_json(response.choices[0].message.content)
    return data.get("shots", [])


async def generate_prompt_profile(
    entity_type: str,
    name: str,
    description: str | None = None,
    style_profile: dict | None = None,
) -> dict:
    """Structured, repeatable visual profile for a character/location/prop (KAN-33).

    Emphasises FIXED, unchanging visual tokens (so the subject reads as the same
    across many generated frames) over narrative description.
    """
    system_prompt = """You are a subject designer for film production. Given a character, location or prop and its description, produce a STRUCTURED, REPEATABLE visual profile — fixed tokens that keep this subject looking identical across many generated frames. Emphasise concrete, unchanging physical attributes (hair, build, face, distinguishing features, materials, wardrobe), NOT narrative, mood, or one-off action.
Return ONLY valid JSON with these keys:
- appearance: array of short visual tokens (the fixed look)
- wardrobe: array of clothing/covering tokens (empty for locations/props if N/A)
- palette: array of colour tokens
- negative: array of things to avoid
- locked_seed: an integer, or null
- notes: a short string
Pure JSON only, no markdown."""

    user = f"Type: {entity_type}\nName: {name}\nDescription: {description or '(none)'}"
    if style_profile:
        user += f"\nProject visual style: {json.dumps(style_profile)}"

    response = await client.chat.completions.create(
        model=LLM_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user},
        ],
        temperature=0.5,
        response_format={"type": "json_object"},
        extra_headers={
            "HTTP-Referer": "https://storyboardpro.local",
            "X-Title": "Storyboard Pro",
        },
    )
    return extract_json(response.choices[0].message.content)


async def generate_style_profile(idea: str, story_summary: str | None = None) -> dict:
    """Project-level visual style, appended to every prompt (KAN-33)."""
    system_prompt = """You are a cinematographer. Given a film idea and story summary, define a single consistent visual STYLE for the whole project.
Return ONLY valid JSON with keys:
- film_stock: short string (e.g. "Kodak Vision3 500T")
- lens: short string (e.g. "35mm anamorphic")
- grade: short string (e.g. "teal-orange, crushed blacks")
- lighting: short string (e.g. "low-key, motivated practicals")
- extra: array of short style tokens
Pure JSON only, no markdown."""

    response = await client.chat.completions.create(
        model=LLM_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Idea: {idea}\n\nStory summary:\n{story_summary or '(none)'}"},
        ],
        temperature=0.5,
        response_format={"type": "json_object"},
        extra_headers={
            "HTTP-Referer": "https://storyboardpro.local",
            "X-Title": "Storyboard Pro",
        },
    )
    return extract_json(response.choices[0].message.content)
