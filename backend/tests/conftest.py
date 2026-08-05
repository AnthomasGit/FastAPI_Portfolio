import os
import uuid
import pytest
import pytest_asyncio
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import selectinload

# Set fake credentials before importing app modules that create OpenAI client
os.environ.setdefault("OPENAI_API_KEY", "sk-test-fake-key")
_test_input_dir = "/tmp/comfy_test_input"
os.environ.setdefault("COMFY_INPUT_DIR", _test_input_dir)
os.makedirs(_test_input_dir, exist_ok=True)
# The background worker must not auto-start under the test ASGI app.
os.environ.setdefault("WORKER_ENABLED", "false")

from database import Base, get_db, Project, Scene, Character, Location, Prop
from main import app


TEST_DB_URL = "sqlite+aiosqlite:///./test.db"


@pytest.fixture
def comfy_api_url():
    return "http://test-comfyui:8188"


@pytest_asyncio.fixture
async def db_engine():
    engine = create_async_engine(TEST_DB_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield engine
    finally:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine):
    session = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)()
    try:
        yield session
    finally:
        await session.close()


@pytest.fixture
def session_factory(db_engine):
    """An async_sessionmaker on the test engine, for code (e.g. the worker) that
    opens its own sessions rather than receiving one via dependency injection."""
    return async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture
async def client(db_session):
    async def override_get_db():
        yield db_session
    app.dependency_overrides[get_db] = override_get_db
    from httpx import AsyncClient, ASGITransport
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def project(db_session):
    p = Project(id=str(uuid.uuid4()), title="Test Project", idea="Test idea")
    db_session.add(p)
    await db_session.commit()
    await db_session.refresh(p)
    return p


@pytest_asyncio.fixture
async def scene(db_session, project):
    s = Scene(id=str(uuid.uuid4()), project_id=project.id, scene_number=1, slugline="Test Scene")
    db_session.add(s)
    await db_session.commit()
    await db_session.refresh(s)
    return s


@pytest_asyncio.fixture
async def character(db_session, project):
    c = Character(id=str(uuid.uuid4()), project_id=project.id, name="Test Character")
    db_session.add(c)
    await db_session.commit()
    await db_session.refresh(c)
    return c


@pytest_asyncio.fixture
async def location(db_session, project):
    l = Location(id=str(uuid.uuid4()), project_id=project.id, name="Test Location")
    db_session.add(l)
    await db_session.commit()
    await db_session.refresh(l)
    return l


@pytest_asyncio.fixture
async def prop(db_session, project):
    p = Prop(id=str(uuid.uuid4()), project_id=project.id, name="Test Prop")
    db_session.add(p)
    await db_session.commit()
    await db_session.refresh(p)
    return p
