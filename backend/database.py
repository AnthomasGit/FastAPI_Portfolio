import os
import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime, JSON, Integer, BigInteger, Table, ForeignKey
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import declarative_base, relationship

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
    Column('character_id', String, ForeignKey('characters.id', ondelete="CASCADE"))
)

scene_locations = Table(
    'scene_locations', Base.metadata,
    Column('scene_id', String, ForeignKey('scenes.id', ondelete="CASCADE")),
    Column('location_id', String, ForeignKey('locations.id', ondelete="CASCADE"))
)

scene_props = Table(
    'scene_props', Base.metadata,
    Column('scene_id', String, ForeignKey('scenes.id', ondelete="CASCADE")),
    Column('prop_id', String, ForeignKey('props.id', ondelete="CASCADE"))
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
    references = relationship("Reference", back_populates="scene", cascade="all, delete-orphan")
    generated_images = relationship("GeneratedImage", back_populates="scene", cascade="all, delete-orphan")


class Character(Base):
    __tablename__ = "characters"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String, ForeignKey('projects.id', ondelete="CASCADE"), nullable=False)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    traits = Column(JSON, nullable=True)
    reference_url = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    project = relationship("Project", back_populates="characters")
    scenes = relationship("Scene", secondary=scene_characters, back_populates="characters")


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


class Prop(Base):
    __tablename__ = "props"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String, ForeignKey('projects.id', ondelete="CASCADE"), nullable=False)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    project = relationship("Project", back_populates="props")
    scenes = relationship("Scene", secondary=scene_props, back_populates="props")


class Reference(Base):
    __tablename__ = "references"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    scene_id = Column(String, ForeignKey('scenes.id', ondelete="CASCADE"), nullable=False)
    url = Column(String, nullable=True)
    description = Column(Text, nullable=True)
    type = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    scene = relationship("Scene", back_populates="references")


class GeneratedImage(Base):
    __tablename__ = "generated_images"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    scene_id = Column(String, ForeignKey('scenes.id', ondelete="SET NULL"), nullable=True)
    project_id = Column(String, ForeignKey('projects.id', ondelete="SET NULL"), nullable=True)
    prompt = Column(Text, nullable=True)
    image_url = Column(String, nullable=True)
    status = Column(String, default="pending")
    job_id = Column(String, nullable=True)
    prompt_id = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    scene = relationship("Scene", back_populates="generated_images")
    project = relationship("Project", back_populates="generated_images")


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
    created_at = Column(DateTime, default=datetime.utcnow)


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db():
    async with SessionLocal() as session:
        yield session
