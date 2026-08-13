from pydantic import BaseModel, model_validator
from typing import Any, Optional, List
from datetime import datetime


class BatchCreateRequest(BaseModel):
    project_id: str
    scope: str  # project | scene | shot | entity
    kind: str  # job kind, e.g. "scene_image"
    target_ids: List[str] = []
    workflow: Optional[str] = None
    chain: Optional[str] = None  # named job chain instead of a single workflow (KAN-47)
    variants: int = 1
    seed_policy: str = "random"
    base_seed: Optional[int] = None
    priority: int = 0
    run_after: Optional[str] = None
    params: dict = {}
    name: Optional[str] = None
    identity_refs: bool = False
    use_plate: bool = True  # feed the scene's location plate as background (KAN-42)
    color_match: bool = False
    color_match_reference: Optional[str] = None
    film_grain: bool = False
    # Per-shot clip audio override (defaults to each shot's own reference_audio_id).
    ref_audio_ids: Optional[List[str]] = None
    # Sheet batches (character_sheet / prop_sheet): override the cell grid, and
    # choose img2img-off-canonical vs a fresh render with `workflow`.
    cells: Optional[List[dict]] = None
    # Alternate outfits are opt-in: names from the character's prompt_profile,
    # one extra cell each. Absent/empty means angles only.
    outfits: Optional[List[str]] = None
    from_canonical: bool = True
    # Location batches: also render the 360 angle set off the new plate.
    with_angles: bool = False
    angles: Optional[List[dict]] = None
    double_ref: bool = True


class PresetCreate(BaseModel):
    name: str
    spec: dict
    project_id: Optional[str] = None  # null = global preset (KAN-48)


class PresetUpdate(BaseModel):
    name: Optional[str] = None
    spec: Optional[dict] = None


class PresetRun(BaseModel):
    overrides: dict = {}  # merged over the stored spec without mutating it


class ProjectCreate(BaseModel):
    title: Optional[str] = None
    idea: str


class ProjectUpdate(BaseModel):
    title: Optional[str] = None
    story_summary: Optional[str] = None
    status: Optional[str] = None


class ProjectListItem(BaseModel):
    id: str
    title: Optional[str] = None
    status: str
    created_at: datetime

    class Config:
        from_attributes = True


class CharacterCreate(BaseModel):
    name: str
    description: Optional[str] = None
    traits: Optional[dict] = None
    reference_url: Optional[str] = None


class CharacterUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    traits: Optional[dict] = None
    reference_url: Optional[str] = None


class CharacterResponse(BaseModel):
    id: str
    project_id: str
    name: str
    description: Optional[str] = None
    traits: Optional[dict] = None
    reference_url: Optional[str] = None
    prompt_profile: Optional[dict] = None

    class Config:
        from_attributes = True

    @model_validator(mode='before')
    @classmethod
    def derive_reference_url(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            try:
                refs = data.references
            except Exception:
                return data
            # No global primary — this is just a display convenience for
            # callers that read reference_url directly (the frontend itself
            # uses the per-scene link's reference_url instead). Newest wins,
            # consistent with the per-scene default (reference_service.
            # newest_reference_id).
            with_url = [r for r in (refs or []) if getattr(r, 'url', None)]
            newest = max(with_url, key=lambda r: r.created_at, default=None)
            if newest:
                return {
                    'id': data.id,
                    'project_id': data.project_id,
                    'name': data.name,
                    'description': data.description,
                    'traits': data.traits,
                    'reference_url': newest.url,
                    'prompt_profile': getattr(data, 'prompt_profile', None),
                }
        return data


class LocationCreate(BaseModel):
    name: str
    description: Optional[str] = None
    shot_notes: Optional[str] = None


class LocationUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    shot_notes: Optional[str] = None


class LocationResponse(BaseModel):
    id: str
    project_id: str
    name: str
    description: Optional[str] = None
    shot_notes: Optional[str] = None
    prompt_profile: Optional[dict] = None
    reference_url: Optional[str] = None

    class Config:
        from_attributes = True

    @model_validator(mode='before')
    @classmethod
    def derive_reference_url(cls, data: Any) -> Any:
        """Newest reference's url — the image an unpicked scene inherits, and the
        UI's "does this asset have art yet" signal. Mirrors CharacterResponse."""
        if isinstance(data, dict):
            return data
        try:
            refs = data.references
        except Exception:
            return data
        with_url = [r for r in (refs or []) if getattr(r, 'url', None)]
        newest = max(with_url, key=lambda r: r.created_at, default=None)
        if not newest:
            return data
        out = {c: getattr(data, c, None) for c in
               ('id', 'project_id', 'name', 'description', 'prompt_profile')}
        out['reference_url'] = newest.url
        if hasattr(data, 'shot_notes'):
            out['shot_notes'] = data.shot_notes
        return out



class PropCreate(BaseModel):
    name: str
    description: Optional[str] = None


class PropUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


class PropResponse(BaseModel):
    id: str
    project_id: str
    name: str
    description: Optional[str] = None
    prompt_profile: Optional[dict] = None
    reference_url: Optional[str] = None

    class Config:
        from_attributes = True

    @model_validator(mode='before')
    @classmethod
    def derive_reference_url(cls, data: Any) -> Any:
        """Newest reference's url — the image an unpicked scene inherits, and the
        UI's "does this asset have art yet" signal. Mirrors CharacterResponse."""
        if isinstance(data, dict):
            return data
        try:
            refs = data.references
        except Exception:
            return data
        with_url = [r for r in (refs or []) if getattr(r, 'url', None)]
        newest = max(with_url, key=lambda r: r.created_at, default=None)
        if not newest:
            return data
        out = {c: getattr(data, c, None) for c in
               ('id', 'project_id', 'name', 'description', 'prompt_profile')}
        out['reference_url'] = newest.url
        if hasattr(data, 'shot_notes'):
            out['shot_notes'] = data.shot_notes
        return out



class ReferenceCreate(BaseModel):
    url: str
    role: str = "moodboard"
    description: Optional[str] = None


class ReferenceUpdate(BaseModel):
    role: Optional[str] = None
    description: Optional[str] = None
    sort_order: Optional[int] = None


def reference_label(ref) -> str:
    """A short, human-distinguishing name for one reference.

    Every generated image carries ``role="moodboard"``, so role alone renders a
    picker as "moodboard, moodboard (1), moodboard (2)…" — useless precisely
    where it matters most, choosing which look a scene uses. Layered, most
    specific first:

      1. the sheet/angle slot   -> "profile", "gala", "detail", "left45"
      2. a prompt excerpt       -> "late 20s male with a…"
      3. upload + date          -> "upload · Jul 27"

    Any ``group:`` prefix is stripped (``outfit:gala`` -> "gala") — the group is
    obvious from context and the trigger is narrow. Older rows may still carry a
    ``wardrobe:``/``materials:`` prefix from retired templates; they strip the
    same way.

    Computed here rather than in the client so every consumer of a reference
    list labels identically, and so the client needs no extra fetch of asset
    images just to draw a dropdown.
    """
    asset = getattr(ref, "asset_image", None)
    params = (getattr(asset, "params", None) or {}) if asset is not None else {}

    slot = params.get("sheet_slot") or params.get("angle_slot")
    if slot:
        return slot.split(":", 1)[1] if ":" in slot else slot

    prompt = (getattr(asset, "prompt", None) or "").strip() if asset is not None else ""
    if prompt:
        if len(prompt) <= 28:
            return prompt
        return prompt[:28].rsplit(" ", 1)[0] + "…"

    created = getattr(ref, "created_at", None)
    stamp = created.strftime("%b %d") if created else ""
    role = getattr(ref, "role", None) or "reference"
    return f"{role} · {stamp}" if stamp else role


class ReferenceResponse(BaseModel):
    id: str
    entity_type: str
    entity_id: str
    role: str
    url: Optional[str] = None
    processed_url: Optional[str] = None
    description: Optional[str] = None
    sort_order: int = 0
    asset_image_id: Optional[str] = None
    # Display name for pickers — see reference_label. Derived, never stored.
    label: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True

    @model_validator(mode="before")
    @classmethod
    def derive_label(cls, data: Any) -> Any:
        if isinstance(data, dict):
            return data
        try:
            label = reference_label(data)
        except Exception:
            # A lazy asset_image load outside a greenlet raises; degrade to the
            # plain row rather than failing the whole response.
            return data
        return {
            "id": data.id,
            "entity_type": data.entity_type,
            "entity_id": data.entity_id,
            "role": data.role,
            "url": data.url,
            "processed_url": data.processed_url,
            "description": data.description,
            "sort_order": data.sort_order,
            "asset_image_id": data.asset_image_id,
            "label": label,
            "created_at": data.created_at,
        }


class AssetImageGenerateRequest(BaseModel):
    project_id: str
    entity_type: str
    entity_id: Optional[str] = None
    prompt: Optional[str] = None
    source_reference_id: Optional[str] = None
    source_asset_image_id: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    # Which txt2img model/workflow to use (see image_workflows.IMAGE_WORKFLOWS);
    # None falls back to the default. img2img ignores this.
    workflow: Optional[str] = None


class AssetImageResponse(BaseModel):
    id: str
    origin_project_id: Optional[str] = None
    entity_type: str
    kind: str = "txt2img"
    source_reference_id: Optional[str] = None
    source_asset_image_id: Optional[str] = None
    prompt: Optional[str] = None
    image_url: Optional[str] = None
    status: str = "queued"
    job_id: Optional[str] = None
    prompt_id: Optional[str] = None
    params: Optional[dict] = None
    error: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class Asset3DMeshGenerateRequest(BaseModel):
    entity_type: str
    entity_id: str
    reference_id: Optional[str] = None
    params: Optional[dict] = None


class VideoGenerateRequest(BaseModel):
    """One clip request, shaped by whichever workflow is selected.

    image_id is optional because reference-driven workflows (LTX-2.3 MSR) need
    no beauty-pass still; the service validates the combination against the
    chosen workflow's declared capabilities rather than trusting the caller.
    """
    workflow: Optional[str] = None
    image_id: Optional[str] = None
    shot_id: Optional[str] = None
    reference_ids: List[str] = []
    background_reference_id: Optional[str] = None
    # MiniMax H3 I2V: the first-frame input image (overrides the still) and an
    # optional last-frame keyframe the clip interpolates toward.
    first_frame_reference_id: Optional[str] = None
    last_frame_reference_id: Optional[str] = None
    driving_video_id: Optional[str] = None
    # MiniMax H3 R2V: up to 3 reference videos (each contributes its own
    # soundtrack) and up to 3 standalone audio clips, alongside reference_ids.
    ref_video_ids: List[str] = []
    ref_audio_ids: List[str] = []
    motion_prompt: Optional[str] = None
    global_prompt: Optional[str] = None
    local_prompts: Optional[str] = None
    params: Optional[dict] = None


class VideoWorkflowSetting(BaseModel):
    """One tunable knob a workflow exposes. Renders generically in the UI:
    a <select> when `options` is set, else a number input/slider bounded by
    `min`/`max`/`step`. See video_service.VIDEO_WORKFLOWS for the full spec
    (backend-only keys like `inject`/`str_value` are stripped before this)."""
    id: str
    label: str
    default: float | int | str
    help: Optional[str] = None
    # int options (LiconMSR frame counts) or string options (sampler/scheduler/
    # aspect-ratio COMBOs on the R2V graph) — a fixed set validated for membership.
    options: Optional[List[int | str]] = None
    min: Optional[float] = None
    max: Optional[float] = None
    step: Optional[float] = None


class VideoWorkflowResponse(BaseModel):
    id: str
    label: str
    blurb: str
    needs_still: bool
    max_refs: int
    max_ref_videos: int = 0
    max_ref_audios: int = 0
    background: bool
    locations_as_refs: bool = False
    first_frame: bool = False
    last_frame: bool = False
    driving_video: bool
    dual_prompt: bool
    settings: List[VideoWorkflowSetting] = []
    est_seconds: int
    recommended: bool = False


class DrivingVideoResponse(BaseModel):
    id: str
    origin_project_id: Optional[str] = None
    label: Optional[str] = None
    video_url: str
    content_type: Optional[str] = None
    size_bytes: Optional[int] = None
    created_at: datetime

    class Config:
        from_attributes = True


class ImageWorkflowResponse(BaseModel):
    """One selectable txt2img model/workflow for the asset-image generator."""
    id: str
    label: str
    blurb: str
    supports_size: bool = True
    recommended: bool = False


class ReferenceAudioResponse(BaseModel):
    id: str
    origin_project_id: Optional[str] = None
    label: Optional[str] = None
    audio_url: str
    content_type: Optional[str] = None
    size_bytes: Optional[int] = None
    created_at: datetime

    class Config:
        from_attributes = True


class GeneratedVideoResponse(BaseModel):
    id: str
    project_id: Optional[str] = None
    scene_id: Optional[str] = None
    source_image_id: Optional[str] = None
    shot_id: Optional[str] = None
    prompt: Optional[str] = None
    video_url: Optional[str] = None
    status: str = "queued"
    job_id: Optional[str] = None
    prompt_id: Optional[str] = None
    params: Optional[dict] = None
    error: Optional[str] = None
    approved_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True


class Asset3DResponse(BaseModel):
    id: str
    project_id: str
    entity_type: str
    entity_id: str
    source_reference_id: Optional[str] = None
    status: str = "queued"
    mesh_url: Optional[str] = None
    rigged_mesh_url: Optional[str] = None
    preview_url: Optional[str] = None
    white_mesh_url: Optional[str] = None
    web_mesh_url: Optional[str] = None
    web_status: Optional[str] = None
    params: Optional[dict] = None
    error: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class AssetImageAssignRequest(BaseModel):
    asset_image_id: str


class SceneStagingUpdate(BaseModel):
    camera: Optional[dict] = None
    blockout: Optional[list] = None
    placements: Optional[list] = None
    backdrop_reference_id: Optional[str] = None
    backdrop_transform: Optional[dict] = None


class SceneStagingResponse(BaseModel):
    id: str
    scene_id: str
    backdrop_reference_id: Optional[str] = None
    backdrop_transform: Optional[dict] = None
    camera: Optional[dict] = None
    blockout: Optional[list] = None
    placements: Optional[list] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class StagingSaveCreate(BaseModel):
    name: str


class StagingSaveResponse(BaseModel):
    id: str
    scene_id: str
    name: str
    created_at: datetime

    class Config:
        from_attributes = True


class SceneCaptureResponse(BaseModel):
    id: str
    staging_id: str
    camera: dict
    staging_snapshot: dict
    depth_map_url: str
    edge_map_url: Optional[str] = None
    color_map_url: Optional[str] = None
    normal_map_url: Optional[str] = None
    seg_map_url: Optional[str] = None
    clean_map_url: Optional[str] = None
    width: int
    height: int
    created_at: datetime
    generated_images: List["GenerateImageResponse"] = []

    class Config:
        from_attributes = True


class ControlledGenerateRequest(BaseModel):
    capture_id: str
    prompt_override: Optional[str] = None
    params: Optional[dict] = None


class GenerateImageResponse(BaseModel):
    id: str
    scene_id: Optional[str] = None
    capture_id: Optional[str] = None
    kind: str = "txt2img"
    prompt: Optional[str] = None
    image_url: Optional[str] = None
    status: str
    job_id: Optional[str] = None
    params: Optional[dict] = None
    error: Optional[str] = None
    created_at: datetime
    # Clips generated from this still; lets the capture panel show the full
    # stage → still → clip lineage and survive a reload.
    videos: List[GeneratedVideoResponse] = []

    class Config:
        from_attributes = True


SceneCaptureResponse.model_rebuild()


class SceneCreate(BaseModel):
    scene_number: int
    slugline: Optional[str] = None
    screenplay: Optional[str] = None
    notes: Optional[str] = None
    sort_order: Optional[int] = 0


class SceneUpdate(BaseModel):
    slugline: Optional[str] = None
    screenplay: Optional[str] = None
    notes: Optional[str] = None


class SceneEntityLink(BaseModel):
    entity_id: str
    reference_id: Optional[str] = None
    reference_url: Optional[str] = None
    # When the chosen reference is a generated asset image, its file lives in
    # ComfyUI's output dir (served via /api/asset-images/{id}/file), not the
    # input-dir static mount that reference_url resolves against. The client
    # needs this to build a working thumbnail URL.
    asset_image_id: Optional[str] = None
    # True once background removal has run — reference_url is then the
    # processed_url (always input-dir-servable), so the client must NOT route
    # through asset_image_id in that case even though it's still set.
    is_processed: bool = False


class SceneEntityLinkUpdate(BaseModel):
    reference_id: Optional[str] = None


class ShotBase(BaseModel):
    shot_number: Optional[str] = None
    sort_order: Optional[int] = 0
    shot_size: Optional[str] = None
    angle: Optional[str] = None
    movement: Optional[str] = None
    description: Optional[str] = None
    equipment: Optional[str] = None
    audio_notes: Optional[str] = None
    capture_id: Optional[str] = None
    generated_image_id: Optional[str] = None
    # Shot-clip batching (H3 reference-to-video).
    reference_audio_id: Optional[str] = None
    audio_role: Optional[str] = None            # 'dialogue' | 'timbre'
    dialogue: Optional[List[dict]] = None       # [{speaker_id, entity_id, language, text}]
    clip_refs: Optional[List[dict]] = None      # ordered [{entity_type, entity_id}]
    clip_prompt: Optional[str] = None


class ShotCreate(ShotBase):
    pass


class ShotUpdate(BaseModel):
    # All optional — PATCH-style partial update. sort_order/reorder handled
    # separately so a field-edit can't accidentally reshuffle the list.
    shot_number: Optional[str] = None
    shot_size: Optional[str] = None
    angle: Optional[str] = None
    movement: Optional[str] = None
    description: Optional[str] = None
    equipment: Optional[str] = None
    audio_notes: Optional[str] = None
    capture_id: Optional[str] = None
    generated_image_id: Optional[str] = None
    reference_audio_id: Optional[str] = None
    audio_role: Optional[str] = None
    dialogue: Optional[List[dict]] = None
    clip_refs: Optional[List[dict]] = None
    clip_prompt: Optional[str] = None


class ShotResponse(ShotBase):
    id: str
    scene_id: str
    created_at: datetime
    # The chosen still (with its clips nested via .videos) so the shot row can
    # render the still + offer its clip without a second fetch.
    still: Optional[GenerateImageResponse] = None
    # Clips generated for the shot directly (reference-driven workflows, which
    # have no source still). The still-derived ones stay under `still.videos`.
    videos: List[GeneratedVideoResponse] = []

    class Config:
        from_attributes = True


class ShotReorderRequest(BaseModel):
    shot_ids: List[str]


class SceneResponse(BaseModel):
    id: str
    project_id: str
    scene_number: int
    slugline: Optional[str] = None
    screenplay: Optional[str] = None
    notes: Optional[str] = None
    sort_order: int
    characters: List[CharacterResponse] = []
    locations: List[LocationResponse] = []
    props: List[PropResponse] = []
    character_links: List[SceneEntityLink] = []
    location_links: List[SceneEntityLink] = []
    prop_links: List[SceneEntityLink] = []
    references: List[ReferenceResponse] = []
    generated_images: List[GenerateImageResponse] = []

    class Config:
        from_attributes = True


class ProjectResponse(BaseModel):
    id: str
    title: Optional[str] = None
    idea: str
    clarifications: Optional[dict] = None
    story_summary: Optional[str] = None
    status: str
    created_at: datetime
    scenes: List[SceneResponse] = []
    characters: List[CharacterResponse] = []
    locations: List[LocationResponse] = []
    props: List[PropResponse] = []

    class Config:
        from_attributes = True


class ClarifyRequest(BaseModel):
    idea: str


class ClarifyResponse(BaseModel):
    questions: List[str]


class GenerateStoryboardRequest(BaseModel):
    idea: str
    answers: dict


class StoryboardResponse(BaseModel):
    project_id: str
    message: str


class SceneReorderRequest(BaseModel):
    scene_ids: List[str]


class GraphNode(BaseModel):
    id: str
    type: str
    label: str
    data: dict


class GraphEdge(BaseModel):
    id: str
    source: str
    target: str
    label: str


class GraphResponse(BaseModel):
    nodes: List[GraphNode]
    edges: List[GraphEdge]
