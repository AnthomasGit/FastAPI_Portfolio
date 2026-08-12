"""H3 full-reference prompt composition for shot clips.

MiniMax H3's reference-to-video mode does not take a sentence — it takes a
**six-section document** (the format guide is vendored at
`backend/reference/h3_full_reference_guide.md`):

    subject_definitions   what each <Subject N> / <Audio N> label denotes
    summary               a [task type] prefix + one paragraph
    retention_analysis    per-label relationship markers
    detailed_description  the shot itself, ~350-500 words
    overall_soundscape    ambience and physical sound
    non_diegetic_music    audience-only score

The single most important invariant:

    reference slot N  ==  image{N} in the graph  ==  <Subject N> in the prompt

so the ordered reference list a shot resolves to *is* the subject numbering.
Compose and inject from the same list or the prompt will describe the wrong
picture — which is why `compose_shot_clip_prompt` takes the resolved entity
list rather than re-deriving it.

Composition is LLM-backed but happens ONCE per shot: the result is stored on
`Shot.clip_prompt` and is user-editable, the same generate-then-edit shape as
`prompt_profile` (KAN-33). Renders read the stored text, so a retry costs
nothing and an overnight batch is reviewable before it runs.
"""
import json
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import Shot, Scene, Project
from services import ai_service
from services.job_handlers import resolve_scene_entities, shot_reference_entities
from services.prompt_builder import entity_prompt, location_prompt, _style_tokens

logger = logging.getLogger(__name__)

# ── Guide vocabulary (data, not branches — retuning is a data edit) ─────────

# Section order is fixed by the guide.
SECTIONS = (
    "subject_definitions",
    "summary",
    "retention_analysis",
    "detailed_description",
    "overall_soundscape",
    "non_diegetic_music",
)

# audio_role -> how the guide describes that audio relationship.
#   task_type      appended to the summary's bracketed prefix
#   marker         the <Audio 1> relationship marker in retention_analysis
#   dialogue_rule  instruction handed to the composer
AUDIO_ROLES = {
    None: {
        "task_type": None,
        "marker": None,
        "dialogue_rule": (
            "No reference audio. Write the shot's dialogue from the supplied "
            "dialogue lines, if any."
        ),
    },
    "dialogue": {
        "task_type": "audio reuse",
        "marker": "fully_copy",
        "dialogue_rule": (
            "<Audio 1> carries the spoken lines and is reused. Preserve the "
            "supplied dialogue text EXACTLY, word for word and in its original "
            "language, inside <d>...</d>. Do not paraphrase or translate it."
        ),
    },
    "timbre": {
        "task_type": "audio reference",
        "marker": "reference",
        "dialogue_rule": (
            "<Audio 1> is a voice-timbre reference only; its signal is NOT "
            "copied. Per the guide, do not carry any dialogue from the "
            "reference audio into the target video — the speaker merely follows "
            "its timbre and delivery."
        ),
    },
}

BASE_TASK_TYPE = "reference generation"
# Identity retention is the entire point of feeding references, so subjects
# default to the strongest marker.
DEFAULT_SUBJECT_MARKER = "fully_preserved"

_SIZE_LABEL = {
    "WS": "wide shot", "MS": "medium shot", "MCU": "medium close-up",
    "CU": "close-up", "ECU": "extreme close-up", "POV": "point-of-view shot",
    "OTS": "over-the-shoulder shot", "Two-Shot": "two-shot",
}
_MOVEMENT_CLAUSE = {
    "Static": "the camera holds steady",
    "Pan": "the camera pans smoothly",
    "Tilt": "the camera tilts",
    "Tracking": "the camera tracks with the subject",
    "Dolly": "the camera dollies",
    "Handheld": "the camera is handheld with subtle instability",
    "Crane": "the camera cranes",
    "Zoom": "the lens zooms",
}


def task_type_prefix(audio_role: str | None) -> str:
    """The guide's bracketed summary prefix, e.g. '[reference generation + audio reuse]'."""
    extra = AUDIO_ROLES.get(audio_role, AUDIO_ROLES[None])["task_type"]
    types = [BASE_TASK_TYPE] + ([extra] if extra else [])
    return f"[{' + '.join(types)}]"


def subject_label(index: int) -> str:
    """Slot index (0-based) -> the guide's 1-based <Subject N> label."""
    return f"<Subject {index + 1}>"


def _entity_tokens(entity_type: str, entity) -> str:
    line = location_prompt(entity) if entity_type == "location" else entity_prompt(entity)
    return line or getattr(entity, "name", "") or ""


def build_subject_brief(entities: list[tuple[str, object]]) -> list[dict]:
    """Slot-numbered brief handed to the composer: what each <Subject N> is.

    Numbering here MUST match the order the same list is injected in — that is
    the contract between the prompt text and the graph's image slots.
    """
    return [
        {
            "label": subject_label(i),
            "slot": i + 1,
            "entity_type": etype,
            "name": getattr(entity, "name", "") or "",
            "tokens": _entity_tokens(etype, entity),
        }
        for i, (etype, entity) in enumerate(entities)
    ]


def render_document(sections: dict) -> str:
    """Serialize the six sections in the guide's fixed order."""
    return "\n\n".join(
        f"{name}:\n{(sections.get(name) or 'N/A').strip()}" for name in SECTIONS
    )


def parse_document(text: str) -> dict:
    """Split a stored document back into its sections (for editing/inspection)."""
    out, current, buf = {}, None, []
    for line in (text or "").splitlines():
        head = line.split(":", 1)[0].strip()
        if head in SECTIONS and line.strip().startswith(head + ":"):
            if current:
                out[current] = "\n".join(buf).strip()
            current = head
            rest = line.split(":", 1)[1].strip()
            buf = [rest] if rest else []
        elif current:
            buf.append(line)
    if current:
        out[current] = "\n".join(buf).strip()
    return out


# ── the swap point ─────────────────────────────────────────────────────────
#
#  compose_shot_clip_prompt is the ONLY place shot-clip prompt wording is
#  decided. Prompt-authoring guidance is expected to change; change it HERE and
#  nowhere else. Keep the signature stable — callers depend on it.
#
# ───────────────────────────────────────────────────────────────────────────

def _system_prompt(audio_role: str | None, has_audio: bool) -> str:
    rules = AUDIO_ROLES.get(audio_role, AUDIO_ROLES[None])
    audio_lines = ""
    if has_audio:
        audio_lines = (
            f"\nThere is one reference audio, labelled <Audio 1>.\n"
            f"- In retention_analysis give it the marker: {rules['marker']}.\n"
            f"- {rules['dialogue_rule']}\n"
        )
    else:
        audio_lines = f"\n{rules['dialogue_rule']}\n"

    return f"""You write prompts for MiniMax H3 video generation in FULL-REFERENCE mode.

Return ONLY valid JSON with exactly these six string keys:
"subject_definitions", "summary", "retention_analysis",
"detailed_description", "overall_soundscape", "non_diegetic_music".

Rules from the format guide:
- Write in English. Keep dialogue and lyrics in their original language inside <d>[Language] ...</d>.
- subject_definitions: put each <Subject N> on ITS OWN LINE, separated by a
  newline character — do not run them together into one paragraph. State what the
  label denotes and the main features to follow. Use the EXACT labels and
  numbering supplied — they map to reference image slots and must not be
  renumbered or reordered.
- summary: begin with the task-type prefix supplied, then one short paragraph
  using the <Subject N> labels. Introduce no new labels here.
- retention_analysis: one line per label, each on its own line, e.g.
  "<Subject 1> (appears in [Shot 1]): {DEFAULT_SUBJECT_MARKER} - ...".
  Use {DEFAULT_SUBJECT_MARKER} for subjects unless told otherwise; retaining the
  referenced likeness is the goal.
- detailed_description: this is ONE single shot. Open with one or two sentences
  establishing visual style, then a single "[Shot 1] ..." block with NO timestamp.

  LENGTH IS A HARD REQUIREMENT: 350-500 words. A short description starves the
  video model and produces a worse clip. Reach the length by DESCRIBING MORE OF
  WHAT IS VISIBLE, never by repeating yourself or padding with plot summary.
  Work through all of the following, roughly a sentence or two each:
    1. framing and composition — what fills the frame, foreground vs background
    2. each <Subject N> at its first appearance: appearance, clothing, exact
       position in frame, posture and facial expression
    3. the environment: architecture, surfaces, props, set dressing, depth cues
    4. lighting: sources, direction, colour temperature, shadows, contrast
    5. the action, as a progression — what changes between the first and last
       frame, including small motions (hands, eyes, breath, fabric)
    6. camera: movement type, amplitude, speed, and any change of focus
    7. texture and atmosphere: materials, reflections, air, motion blur
    8. diegetic sound occurring within the shot
  Insert each <Subject N> at its first clear appearance. Do not summarize plot or
  list reference relationships instead of describing what is visible.
- Give each vocal source a stable (S1), (S2)... in order of vocal events, and
  write a speaking subject as "<Subject N> (Sx)".
- overall_soundscape: ambience and physical sound. non_diegetic_music: audience-only
  score, or "N/A".
{audio_lines}
Pure JSON only, no markdown."""


def _user_prompt(shot, scene, project, subjects: list[dict], dialogue: list[dict] | None,
                 audio_role: str | None, has_audio: bool) -> str:
    subject_lines = "\n".join(
        f"{s['label']} = {s['entity_type']} \"{s['name']}\""
        + (f" — {s['tokens']}" if s["tokens"] else "")
        for s in subjects
    ) or "(no reference subjects)"

    dialogue_lines = "\n".join(
        f"({d.get('speaker_id') or 'S?'}) [{d.get('language') or 'English'}] {d.get('text') or ''}"
        for d in (dialogue or [])
    ) or "(none)"

    movement = _MOVEMENT_CLAUSE.get(shot.movement or "", "")
    size = _SIZE_LABEL.get(shot.shot_size or "", shot.shot_size or "")

    return f"""Task type prefix to use verbatim in `summary`: {task_type_prefix(audio_role)}

REFERENCE SUBJECTS (labels are fixed — use exactly these):
{subject_lines}
{"AUDIO: <Audio 1> is attached to this shot." if has_audio else "AUDIO: none attached."}

SHOT
  number: {shot.shot_number or "(unnumbered)"}
  size: {size or "(unspecified)"}
  angle: {shot.angle or "(unspecified)"}
  camera movement: {shot.movement or "(unspecified)"}{f" — {movement}" if movement else ""}
  action/description: {shot.description or "(none given)"}
  audio notes: {shot.audio_notes or "(none)"}

DIALOGUE for this shot (use verbatim inside <d>):
{dialogue_lines}

SCENE
  slugline: {getattr(scene, "slugline", "") or "(none)"}
  screenplay:
{(getattr(scene, "screenplay", "") or "(none)")[:4000]}

VISUAL STYLE: {_style_tokens(project)}"""


class PromptCompositionError(RuntimeError):
    """The model did not return a usable document. Carries which model, since
    LLM_MODEL may be a routing alias that lands on a different one each call."""


def _document_from_response(response) -> str:
    """Turn a completion into the six-section document, or raise.

    Deliberately tolerant of two real failure modes seen with routed/free models:
      * `content` is None — typical of reasoning models that spend their token
        budget on reasoning and emit nothing (the raw AttributeError this used
        to produce told the operator nothing);
      * the model ignored the JSON instruction and returned the document as
        prose — recoverable, because the sections are self-labelling.
    """
    model = getattr(response, "model", None) or ai_service.LLM_MODEL
    choice = response.choices[0] if response.choices else None
    content = getattr(getattr(choice, "message", None), "content", None)

    if not content or not content.strip():
        reason = "returned empty content"
        if getattr(getattr(choice, "message", None), "reasoning", None):
            reason += " (reasoning-only response — the model spent its budget thinking)"
        raise PromptCompositionError(f"{model} {reason}")

    try:
        return render_document(ai_service.extract_json(content))
    except Exception:
        # Not JSON — accept prose if it actually carries the sections.
        parsed = parse_document(content)
        if len(parsed) >= 3:
            return render_document(parsed)
        raise PromptCompositionError(
            f"{model} returned neither JSON nor a sectioned document "
            f"(first 200 chars: {content.strip()[:200]!r})"
        ) from None


async def compose_shot_clip_prompt(shot, scene, entities: list[tuple[str, object]],
                                   project, *, dialogue: list[dict] | None = None,
                                   has_audio: bool = False, attempts: int = 2) -> str:
    """Compose the six-section H3 document for one shot. Returns the document.

    `entities` is the ORDERED, already-resolved reference list — the same list
    that fills the graph's image slots, so <Subject N> lines up with image{N}.

    Retried once by default: when LLM_MODEL is a routing alias (e.g.
    ``openrouter/free``) each call can land on a different model, so a single
    unusable response says nothing about the next one.
    """
    subjects = build_subject_brief(entities)
    audio_role = shot.audio_role if has_audio else None
    messages = [
        {"role": "system", "content": _system_prompt(audio_role, has_audio)},
        {"role": "user", "content": _user_prompt(shot, scene, project, subjects,
                                                 dialogue, audio_role, has_audio)},
    ]

    last: Exception | None = None
    for attempt in range(max(1, attempts)):
        try:
            response = await ai_service.client.chat.completions.create(
                model=ai_service.LLM_MODEL,
                messages=messages,
                temperature=0.7,
                response_format={"type": "json_object"},
                extra_headers={
                    "HTTP-Referer": "https://storyboardpro.local",
                    "X-Title": "Storyboard Pro",
                },
            )
            return _document_from_response(response)
        except PromptCompositionError as e:
            last = e
            logger.warning("shot %s prompt attempt %d/%d failed: %s",
                           shot.id, attempt + 1, attempts, e)
    raise last


async def extract_scene_dialogue(scene, entities: list[tuple[str, object]],
                                 shots: list) -> dict[str, list[dict]]:
    """Split a scene's screenplay dialogue across its shots.

    Returns {shot_id: [{speaker_id, entity_id, language, text}]}. Speaker ids are
    assigned in order of vocal events across the whole scene and bound to a
    character subject via entity_id where possible, so a line keeps the same
    (Sx) in every shot it spans.
    """
    characters = [(e.id, e.name) for etype, e in entities if etype == "character"]
    if not shots:
        return {}

    roster = "\n".join(f"- {name} (entity_id: {cid})" for cid, name in characters) or "(none)"
    shot_list = "\n".join(
        f"- shot_id {s.id}: {s.shot_number or '?'} — {s.description or '(no description)'}"
        for s in shots
    )
    system = """You assign a film scene's spoken lines to specific shots.

Return ONLY valid JSON: {"shots": {"<shot_id>": [{"speaker_id": "S1",
"entity_id": "<character entity_id or null>", "language": "English",
"text": "<the spoken line, verbatim>"}]}}

Rules:
- Use ONLY dialogue actually present in the screenplay. Never invent lines.
- Preserve each line's original wording and language exactly.
- Assign speaker ids S1, S2, ... in order of first vocal event across the scene,
  and reuse the same id for the same speaker in every shot.
- Bind speaker_id to a character's entity_id when the speaker is on the roster;
  otherwise use null.
- A shot with no dialogue gets an empty array. Pure JSON only."""

    user = f"""CHARACTER ROSTER:
{roster}

SHOTS:
{shot_list}

SCREENPLAY:
{(getattr(scene, "screenplay", "") or "(none)")[:6000]}"""

    response = await ai_service.client.chat.completions.create(
        model=ai_service.LLM_MODEL,
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": user}],
        temperature=0.2,  # extraction, not invention
        response_format={"type": "json_object"},
        extra_headers={
            "HTTP-Referer": "https://storyboardpro.local",
            "X-Title": "Storyboard Pro",
        },
    )
    data = ai_service.extract_json(response.choices[0].message.content)
    return data.get("shots", {}) or {}


# ── orchestration ──────────────────────────────────────────────────────────

async def _load_context(shot, db: AsyncSession):
    scene = await db.get(Scene, shot.scene_id)
    project = await db.get(Project, scene.project_id) if scene else None
    entities = await resolve_scene_entities(shot.scene_id, db) if scene else []
    return scene, project, entities


async def compose_for_shot(shot: Shot, db: AsyncSession, *, force: bool = False) -> str:
    """Compose and persist `shot.clip_prompt`. Returns the document.

    Honours an existing prompt unless `force` — the stored text is user-editable
    and a regenerate must be explicit, never a side effect of rendering.
    """
    if shot.clip_prompt and not force:
        return shot.clip_prompt

    scene, project, _all = await _load_context(shot, db)
    # Exactly the entities the graph will receive, in slot order: filtered to
    # those with a primary image and capped at the workflow's slot count. The
    # prompt must describe the images that will actually be injected, not every
    # entity linked to the scene.
    from services.shot_clip_service import DEFAULT_SHOT_CLIP_WORKFLOW
    from services.video_service import VIDEO_WORKFLOWS
    max_refs = VIDEO_WORKFLOWS[DEFAULT_SHOT_CLIP_WORKFLOW].get("max_refs")
    entities = await shot_reference_entities(shot, db, max_refs=max_refs)

    doc = await compose_shot_clip_prompt(
        shot, scene, entities, project,
        dialogue=shot.dialogue,
        has_audio=bool(shot.reference_audio_id),
    )
    shot.clip_prompt = doc
    await db.commit()
    return doc


async def compose_for_scene(scene_id: str, db: AsyncSession, *, force: bool = False) -> dict:
    """Extract dialogue for a scene, then compose every shot's prompt.

    Dialogue is extracted once for the whole scene so speaker ids stay
    consistent across shots, then each shot's document is composed from it.
    """
    scene = await db.get(Scene, scene_id)
    if scene is None:
        return {"composed": 0, "shots": []}
    shots = (await db.execute(
        select(Shot).where(Shot.scene_id == scene_id).order_by(Shot.sort_order)
    )).scalars().all()
    if not shots:
        return {"composed": 0, "shots": []}

    entities = await resolve_scene_entities(scene_id, db)

    pending = [s for s in shots if force or not s.dialogue]
    if pending:
        try:
            by_shot = await extract_scene_dialogue(scene, entities, pending)
            for s in pending:
                lines = by_shot.get(s.id)
                if lines is not None:
                    s.dialogue = lines
            await db.commit()
        except Exception:
            # Dialogue is an enhancement — a failure here must not block the
            # prompts, which are the thing a render actually needs.
            logger.exception("dialogue extraction failed for scene %s; continuing", scene_id)

    composed, failed = [], []
    for s in shots:
        try:
            await compose_for_shot(s, db, force=force)
            composed.append(s.id)
        except Exception as e:
            # One bad shot must not block the rest, but the caller has to learn
            # WHY — a bare composed:0 is indistinguishable from a timeout.
            logger.exception("prompt composition failed for shot %s", s.id)
            failed.append({"shot_id": s.id, "shot_number": s.shot_number,
                           "reason": str(e)[:300]})
    return {"composed": len(composed), "shots": composed,
            "failed": failed, "model": ai_service.LLM_MODEL}
