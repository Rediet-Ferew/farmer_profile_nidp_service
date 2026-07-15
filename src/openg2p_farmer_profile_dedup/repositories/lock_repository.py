from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class LockRepository:
    """PostgreSQL advisory lock helper."""

    async def acquire(self, session: AsyncSession, lock_id: int) -> bool:
        result = await session.execute(
            text("SELECT pg_try_advisory_lock(:lock_id) AS acquired"),
            {"lock_id": lock_id},
        )
        row = result.mappings().first()
        return bool(row and row["acquired"])

    async def release(self, session: AsyncSession, lock_id: int) -> None:
        await session.execute(
            text("SELECT pg_advisory_unlock(:lock_id)"),
            {"lock_id": lock_id},
        )
