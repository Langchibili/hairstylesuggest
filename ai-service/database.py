"""
MySQL connection pool — async via aiomysql.

Usage:
    from database import get_pool

    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute("SELECT 1")
"""

import aiomysql
from loguru import logger
from config import settings

_pool: aiomysql.Pool | None = None


async def init_pool() -> None:
    """Create the global connection pool. Called once at startup."""
    global _pool
    _pool = await aiomysql.create_pool(
        host=settings.database_host,
        port=settings.database_port,
        db=settings.database_name,
        user=settings.database_user,
        password=settings.database_password,
        minsize=2,
        maxsize=10,
        cursorclass=aiomysql.DictCursor,
        autocommit=False,
        connect_timeout=10,
        echo=False,
        charset="utf8mb4",
    )
    logger.info(
        f"MySQL pool created → {settings.database_host}:{settings.database_port}"
        f"/{settings.database_name}"
    )


async def get_pool() -> aiomysql.Pool:
    """Return the pool, raising if not initialised."""
    if _pool is None:
        raise RuntimeError("MySQL pool is not initialised. Call init_pool() first.")
    return _pool


async def close_pool() -> None:
    """Gracefully close the pool. Called at shutdown."""
    global _pool
    if _pool:
        _pool.close()
        await _pool.wait_closed()
        _pool = None
        logger.info("MySQL pool closed")


async def claim_job(pool: aiomysql.Pool) -> dict | None:
    """
    Atomically claim the oldest queued job using SELECT FOR UPDATE SKIP LOCKED.

    SKIP LOCKED means concurrent workers never block each other.
    Returns the job row as a dict, or None if the queue is empty.
    """
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            try:
                await cur.execute("START TRANSACTION")

                await cur.execute(
                    """
                    SELECT id, session_id, type, status, payload,
                           attempt_count, queued_at, error_message
                    FROM jobs
                    WHERE status IN ('queued', 'retrying')
                      AND attempt_count < %s
                    ORDER BY queued_at ASC
                    LIMIT 1
                    FOR UPDATE SKIP LOCKED
                    """,
                    (settings.job_max_attempts,),
                )
                job = await cur.fetchone()

                if job:
                    await cur.execute(
                        """
                        UPDATE jobs
                        SET status = 'running',
                            started_at = NOW(),
                            attempt_count = attempt_count + 1
                        WHERE id = %s
                        """,
                        (job["id"],),
                    )
                    await conn.commit()
                    logger.info(
                        f"[db] Claimed job {job['id']} | type={job['type']} "
                        f"| attempt={job['attempt_count'] + 1}"
                    )
                else:
                    await conn.commit()

                return job

            except Exception as exc:
                await conn.rollback()
                logger.error(f"[db] claim_job failed: {exc}")
                raise


async def mark_job_failed(
    pool: aiomysql.Pool,
    job_id: str,
    error_message: str,
    attempt_count: int,
) -> None:
    """Mark a job as failed or retrying based on attempt count."""
    status = "failed" if attempt_count >= settings.job_max_attempts else "retrying"

    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                UPDATE jobs
                SET status = %s,
                    error_message = %s,
                    attempt_count = %s,
                    completed_at = CASE WHEN %s = 'failed' THEN NOW() ELSE NULL END
                WHERE id = %s
                """,
                (status, error_message, attempt_count, status, job_id),
            )
            await conn.commit()

    logger.warning(
        f"[db] Job {job_id} → {status} "
        f"(attempt {attempt_count}/{settings.job_max_attempts}): {error_message[:120]}"
    )
