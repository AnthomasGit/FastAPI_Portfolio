import os
import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, BigInteger, DateTime, JSON
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import declarative_base

# Grabs the URL from docker-compose, or defaults to localhost if running bare metal
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://portfolio_user:supersecretpassword@localhost:5432/portfolio_db"
)

# The async engine manages our connection pool to Postgres
engine = create_async_engine(DATABASE_URL, echo=False)

# The session factory generates async database sessions for our endpoints
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

Base = declarative_base()

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
    """Utility function to initialize the tables on startup"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)