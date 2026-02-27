import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

URL = "postgresql+asyncpg://postgres:postgres@localhost:5434/test_knowledge_agent"

async def main():
    engine = create_async_engine(URL)
    async with engine.connect() as conn:
        result = await conn.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")
        )
        tables = [row[0] for row in result.fetchall()]
        print("Tables in test_knowledge_agent:")
        for t in tables:
            print(" ", t)
    await engine.dispose()

asyncio.run(main())
