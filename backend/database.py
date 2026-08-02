import os
import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime, JSON, Integer, BigInteger, Table, ForeignKey, Index
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import declarative_base, relationship, backref

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://portfolio_user:supersecretpassword@localhost:5432/portfolio_db"
)

engine = create_async_engine(DATABASE_URL, echo=False)

SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

Base = declarative_base()

scene_characters = Table(
    'scene_characters', Base.metadata,
    Column('scene_id', String, ForeignKey('scenes.id', ondelete="CASCADE")),
    Column('character_id', String, ForeignKey('characters.id', ondelete="CASCADE")),
    Column('reference_id', String, ForeignKey('references.id', ondelete="SET NULL"), nullable=True)
)

scene_locations = Table(
    'scene_locations', Base.metadata,
    Column('scene_id', String, ForeignKey('scenes.id', ondelete="CASCADE")),
    Column('location_id', String, ForeignKey('locations.id', ondelete="CASCADE")),
    Column('reference_id', String, ForeignKey('references.id', ondelete="SET NULL"), nullable=True)
)

scene_props = Table(
    'scene_props', Base.metadata,
    Column('scene_id', String, ForeignKey('scenes.id', ondelete="CASCADE")),
    Column('prop_id', String, ForeignKey('props.id', ondelete="CASCADE")),
    Column('reference_id', String, ForeignKey('references.id', ondelete="SET NULL"), nullable=True)
)


class Project(Base):
    __tablename__ = "projects"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    title = Column(String, nullable=True)
    idea = Column(Text, nullable=False)
    clarifications = Column(JSON, nullable=True)
    story_summary = Column(Text, nullable=True)
    status = Column(String, default="draft")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    scenes = relationship("Scene", back_populates="project", cascade="all, delete-orphan")
    characters = relationship("Character", back_populates="project", cascade="all, delete-orphan")
    locations = relationship("Location", back_populates="project", cascade="all, delete-orphan")
    props = relationship("Prop", back_populates="project", cascade="all, delete-orphan")
    generated_images = relationship("GeneratedImage", back_populates="project", cascade="all, delete-orphan")
    asset_images = relationship("AssetImage", back_populates="project", cascade="all, delete-orphan")
    assets_3d = relationship("Asset3D", back_populates="project", cascade="all, delete-orphan")


class Scene(Base):
    __tablename__ = "scenes"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String, ForeignKey('projects.id', ondelete="CASCADE"), nullable=False)
    scene_number = Column(Integer)
    slugline = Column(String, nullable=True)
    screenplay = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    project = relationship("Project", back_populates="scenes")
    characters = relationship("Character", secondary=scene_characters, back_populates="scenes")
    locations = relationship("Location", secondary=scene_locations, back_populates="scenes")
    props = relationship("Prop", secondary=scene_props, back_populates="scenes")
    references = relationship(
        "Reference",
        primaryjoin="and_(foreign(Reference.entity_id)==Scene.id, Reference.entity_type=='scene')",
        viewonly=False, cascade="all, delete-orphan", overlaps="references",
    )
    generated_images = relationship("GeneratedImage", back_populates="scene", cascade="all, delete-orphan")
    staging = relationship("SceneStaging", back_populates="scene", uselist=False, cascade="all, delete-orphan")
    shots = relationship("Shot", back_populates="scene", cascade="all, delete-orphan",
                         order_by="Shot.sort_order")


class Character(Base):
    __tablename__ = "characters"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String, ForeignKey('projects.id', ondelete="CASCADE"), nullable=False)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    traits = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    project = relationship("Project", back_populates="characters")
    scenes = relationship("Scene", secondary=scene_characters, back_populates="characters")
    references = relationship(
        "Reference",
        primaryjoin="and_(foreign(Reference.entity_id)==Character.id, Reference.entity_type=='character')",
        viewonly=False, cascade="all, delete-orphan", overlaps="references",
    )


class Location(Base):
    __tablename__ = "locations"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String, ForeignKey('projects.id', ondelete="CASCADE"), nullable=False)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    shot_notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    project = relationship("Project", back_populates="locations")
    scenes = relationship("Scene", secondary=scene_locations, back_populates="locations")
    references = relationship(
        "Reference",
        primaryjoin="and_(foreign(Reference.entity_id)==Location.id, Reference.entity_type=='location')",
        viewonly=False, cascade="all, delete-orphan", overlaps="references",
    )


class Prop(Base):
    __tablename__ = "props"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String, ForeignKey('projects.id', ondelete="CASCADE"), nullable=False)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    project = relationship("Project", back_populates="props")
    scenes = relationship("Scene", secondary=scene_props, back_populates="props")
    references = relationship(
        "Reference",
        primaryjoin="and_(foreign(Reference.entity_id)==Prop.id, Reference.entity_type=='prop')",
        viewonly=False, cascade="all, delete-orphan", overlaps="references",
    )


class Reference(Base):
    __tablename__ = "references"
    __table_args__ = (
        Index("ix_references_entity", "entity_type", "entity_id"),
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    entity_type = Column(String, nullable=False)
    entity_id = Column(String, nullable=False)
    role = Column(String, nullable=False, default="moodboard")
    url = Column(String, nullable=True)
    processed_url = Column(String, nullable=True)
    description = Column(Text, nullable=True)
    sort_order = Column(Integer, default=0)
    asset_image_id = Column(String, ForeignKey("asset_images.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    asset_image = relationship("AssetImage", foreign_keys=[asset_image_id], back_populates="references")


class AssetImage(Base):
    __tablename__ = "asset_images"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    origin_project_id = Column(String, ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)
    entity_type = Column(String, nullable=False)   # 'character' | 'location' | 'prop'
    kind = Column(String, nullable=False, default="txt2img")  # 'txt2img' | 'img2img'
    source_reference_id = Column(String, ForeignKey("references.id", ondelete="SET NULL"), nullable=True)
    source_asset_image_id = Column(String, ForeignKey("asset_images.id", ondelete="SET NULL"), nullable=True)
    prompt = Column(Text, nullable=True)
    image_url = Column(String, nullable=True)
    status = Column(String, default="queued")
    job_id = Column(String, nullable=True)
    prompt_id = Column(String, nullable=True)
    params = Column(JSON, nullable=True)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    project = relationship("Project", back_populates="asset_images")
    source_reference = relationship("Reference", foreign_keys=[source_reference_id])
    source_asset_image = relationship("AssetImage", foreign_keys=[source_asset_image_id], remote_side="AssetImage.id")
    references = relationship("Reference", foreign_keys="Reference.asset_image_id", back_populates="asset_image")


class GeneratedImage(Base):
    __tablename__ = "generated_images"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    scene_id = Column(String, ForeignKey('scenes.id', ondelete="SET NULL"), nullable=True)
    project_id = Column(String, ForeignKey('projects.id', ondelete="SET NULL"), nullable=True)
    capture_id = Column(String, ForeignKey("scene_captures.id", ondelete="SET NULL"), nullable=True)
    kind = Column(String, default="txt2img")
    prompt = Column(Text, nullable=True)
    image_url = Column(String, nullable=True)
    status = Column(String, default="pending")
    job_id = Column(String, nullable=True)
    prompt_id = Column(String, nullable=True)
    params = Column(JSON, nullable=True)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    scene = relationship("Scene", back_populates="generated_images")
    project = relationship("Project", back_populates="generated_images")
    capture = relationship("SceneCapture", back_populates="generated_images")
    # selectin (not the default lazy load) so `.videos` is always safe to read
    # during async serialization — GenerateImageResponse exposes it on every
    # endpoint that returns a still, and a plain lazy load there raises
    # MissingGreenlet. Clips are few and append-only, so the extra batched
    # SELECT is cheap.
    videos = relationship(
        "GeneratedVideo", back_populates="source_image", lazy="selectin"
    )


class GeneratedVideo(Base):
    """Append-only video attempt, mirroring GeneratedImage.

    Two provenances, depending on the workflow (see video_service.VIDEO_WORKFLOWS):
    image-to-video consumes a completed GeneratedImage (the beauty pass output),
    never a raw capture — the stage dependency rule in 3d-staging-lld-sdlc.md.
    Multi-subject-reference workflows need no still at all and instead compose
    reference images directly, so their clip hangs off ``shot_id``. Exactly one
    of the two is set in practice, and both are nullable.
    """
    __tablename__ = "generated_videos"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String, ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)
    scene_id = Column(String, ForeignKey("scenes.id", ondelete="SET NULL"), nullable=True)
    source_image_id = Column(String, ForeignKey("generated_images.id", ondelete="SET NULL"), nullable=True)
    shot_id = Column(String, ForeignKey("shots.id", ondelete="SET NULL"), nullable=True, index=True)
    prompt = Column(Text, nullable=True)                 # motion prompt
    video_url = Column(String, nullable=True)            # MP4/WebM filename in ComfyUI output
    status = Column(String, default="queued")            # queued|processing|completed|failed
    job_id = Column(String, nullable=True)
    prompt_id = Column(String, nullable=True)
    params = Column(JSON, nullable=True)                 # {workflow, frames, fps, seed}
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    source_image = relationship("GeneratedImage", back_populates="videos")


class Shot(Base):
    """One planned shot in a scene's master shot list.

    Metadata (shot_size/angle/movement/audio_notes) is load-bearing, not just
    documentation — it composes into the LTX motion prompt when a clip is
    generated. Scene # is derived from the parent scene, not stored here.

    Clips reach a shot two ways and there is deliberately no
    generated_video_id column for either: image-to-video clips derive from
    generated_image_id -> .videos (newest completed), while reference-driven
    workflows that need no still attach straight to this row via
    GeneratedVideo.shot_id -> .videos. Both are append-only attempt lists.
    """
    __tablename__ = "shots"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    scene_id = Column(String, ForeignKey("scenes.id", ondelete="CASCADE"), nullable=False)
    shot_number = Column(String, nullable=True)          # "1A", "1B", ...
    sort_order = Column(Integer, default=0)
    shot_size = Column(String, nullable=True)            # WS | MS | CU | ECU | POV | ...
    angle = Column(String, nullable=True)                # High | Eye-Level | Low | ...
    movement = Column(String, nullable=True)             # Static | Tracking | Handheld | ...
    description = Column(Text, nullable=True)
    equipment = Column(String, nullable=True)
    audio_notes = Column(Text, nullable=True)
    # The capture this shot was framed from (optional — a shot can be planned
    # before anything is staged), and the beauty-pass still chosen for it.
    capture_id = Column(String, ForeignKey("scene_captures.id", ondelete="SET NULL"), nullable=True)
    generated_image_id = Column(String, ForeignKey("generated_images.id", ondelete="SET NULL"),
                                nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    scene = relationship("Scene", back_populates="shots")
    capture = relationship("SceneCapture")
    generated_image = relationship("GeneratedImage")
    # selectin, not lazy: these are serialized inside an async response and a
    # lazy load there raises MissingGreenlet (same reason as GeneratedImage.videos).
    videos = relationship(
        "GeneratedVideo",
        lazy="selectin",
        order_by="GeneratedVideo.created_at.desc()",
    )


class Asset3D(Base):
    __tablename__ = "assets_3d"
    __table_args__ = (Index("ix_assets3d_entity", "entity_type", "entity_id"),)

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    entity_type = Column(String, nullable=False)          # 'character' | 'prop'
    entity_id = Column(String, nullable=False)
    source_reference_id = Column(String, ForeignKey("references.id", ondelete="SET NULL"), nullable=True)

    status = Column(String, default="queued")
    # queued | mesh_processing | mesh_ready | rig_queued | rig_processing
    # | rigged | mesh_failed | rig_failed

    mesh_url = Column(String, nullable=True)              # textured GLB filename in ComfyUI output
    white_mesh_url = Column(String, nullable=True)        # untextured base GLB (reusable for re-texturing)
    rigged_mesh_url = Column(String, nullable=True)       # rigged GLB filename
    preview_url = Column(String, nullable=True)

    web_mesh_url = Column(String, nullable=True)          # optimized web GLB (meshopt+webp), served transparently
    web_status = Column(String, nullable=True)            # None | processing | ready | failed

    mesh_job_id = Column(String, nullable=True)
    rig_job_id = Column(String, nullable=True)
    params = Column(JSON, nullable=True)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    project = relationship("Project", back_populates="assets_3d")


class SceneStaging(Base):
    __tablename__ = "scene_stagings"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    scene_id = Column(String, ForeignKey("scenes.id", ondelete="CASCADE"),
                      nullable=False, unique=True)
    backdrop_reference_id = Column(String, ForeignKey("references.id", ondelete="SET NULL"),
                                   nullable=True)
    backdrop_transform = Column(JSON, nullable=True)
    camera = Column(JSON, nullable=True)
    blockout = Column(JSON, nullable=True)
    placements = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    scene = relationship("Scene", back_populates="staging")
    captures = relationship("SceneCapture", back_populates="staging",
                            cascade="all, delete-orphan")


class SceneCapture(Base):
    __tablename__ = "scene_captures"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    staging_id = Column(String, ForeignKey("scene_stagings.id", ondelete="CASCADE"), nullable=False)
    camera = Column(JSON, nullable=False)
    staging_snapshot = Column(JSON, nullable=False)
    depth_map_url = Column(String, nullable=False)
    edge_map_url = Column(String, nullable=True)
    color_map_url = Column(String, nullable=True)
    normal_map_url = Column(String, nullable=True)
    seg_map_url = Column(String, nullable=True)
    clean_map_url = Column(String, nullable=True)
    width = Column(Integer, nullable=False)
    height = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    staging = relationship("SceneStaging", back_populates="captures")
    generated_images = relationship("GeneratedImage", back_populates="capture")


class StagingSave(Base):
    __tablename__ = "staging_saves"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    scene_id = Column(String, ForeignKey("scenes.id", ondelete="CASCADE"), nullable=False)
    name = Column(String, nullable=False)
    backdrop_reference_id = Column(String, ForeignKey("references.id", ondelete="SET NULL"),
                                   nullable=True)
    backdrop_transform = Column(JSON, nullable=True)
    camera = Column(JSON, nullable=True)
    blockout = Column(JSON, nullable=True)
    placements = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class JobRecord(Base):
    __tablename__ = "jobs"

    job_id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    prompt_id = Column(String, nullable=True)
    status = Column(String, default="queued")
    model_name = Column(String, nullable=False)
    query = Column(Text, nullable=False)
    seed = Column(BigInteger, nullable=True)
    image_url = Column(String, nullable=True)
    image_info = Column(JSON, nullable=True)
    job_type = Column(String, nullable=False, default="image")
    # 'image' | 'controlled_image' | 'mesh' | 'rig' | 'video'
    entity_type = Column(String, nullable=True)
    entity_id = Column(String, nullable=True)
    error = Column(Text, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db():
    async with SessionLocal() as session:
        yield session
