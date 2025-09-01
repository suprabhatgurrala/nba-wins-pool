import os
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine, AsyncSession
from sqlalchemy import text

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/nba_wins_pool")

engine: AsyncEngine = create_async_engine(DATABASE_URL, echo=True)


async def test_connection():
    """Test database connection"""
    try:
        async with engine.begin() as conn:
            result = await conn.execute(text("SELECT 1"))
            return True
    except Exception as e:
        print(f"Database connection failed: {e}")
        return False


async def get_db_session() -> AsyncSession:
    """Database session dependency"""
    async with AsyncSession(engine) as session:
        yield session
