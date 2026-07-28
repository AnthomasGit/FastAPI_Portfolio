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
