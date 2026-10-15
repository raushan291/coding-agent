from __future__ import annotations

import asyncio
from urllib.parse import urlparse

from redis.asyncio import Redis
from rich.console import Console

from coding_agent.config import config
from coding_agent.observability.logger import get_logger

logger = get_logger(__name__)

console = Console()

DEFAULT_REDIS_IMAGE = "redis/redis-stack-server:latest"
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", ""}


def _redis_target(redis_url: str) -> tuple[str, int]:
    parsed = urlparse(redis_url)
    host = parsed.hostname or "localhost"
    port = parsed.port or 6379
    return host, port


async def _ping(redis_url: str, timeout: float = 1.0) -> bool:
    client = Redis.from_url(
        redis_url, socket_connect_timeout=timeout, socket_timeout=timeout
    )
    try:
        await client.ping()
        return True
    except Exception:
        return False
    finally:
        await client.aclose()


async def _run_docker(*args: str) -> bool:
    """Run a docker command, returning True on a zero exit code.

    FileNotFoundError (docker not installed) and any non-zero exit are
    reported as False so the caller can fall back gracefully.
    """
    try:
        process = await asyncio.create_subprocess_exec(
            "docker",
            *args,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        return await process.wait() == 0
    except FileNotFoundError:
        logger.warning("Redis auto-start: docker is not installed or not on PATH")
        return False
    except Exception as error:
        logger.warning(f"Redis auto-start: docker command failed: {error}")
        return False


async def _start_redis(container_name: str, host: str, port: int) -> None:
    if await _run_docker("start", container_name):
        return
    if host not in LOCAL_HOSTS:
        logger.warning(
            f"Redis auto-start: container '{container_name}' is absent and "
            f"redis_url host '{host}' is not local, so it cannot be started"
        )
        return
    await _run_docker(
        "run",
        "-d",
        "--name",
        container_name,
        "-p",
        f"{port}:6379",
        DEFAULT_REDIS_IMAGE,
    )


async def ensure_redis() -> None:
    """Start Redis automatically when the semantic cache is enabled but Redis
    is unreachable. Best-effort: any failure leaves the cache disabled rather
    than aborting startup.
    """
    cache_config = config.get("semantic_cache", {})
    if not cache_config.get("enabled", False):
        return
    if not cache_config.get("auto_start", False):
        return

    redis_url = cache_config.get("redis_url", "redis://localhost:6379")
    if await _ping(redis_url):
        return

    host, port = _redis_target(redis_url)
    container_name = cache_config.get("container_name", "redis-stack")
    timeout = cache_config.get("start_timeout", 20)

    console.print("[dim]Redis not reachable - starting it...[/dim]")
    logger.info(f"Redis auto-start: launching container '{container_name}'")

    await _start_redis(container_name, host, port)

    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if await _ping(redis_url):
            console.print("[dim]Redis is up.[/dim]")
            logger.info("Redis auto-start: ready")
            return
        await asyncio.sleep(0.5)

    console.print(
        f"[yellow]Redis did not become ready within {timeout}s - "
        "semantic cache stays disabled.[/yellow]"
    )
    logger.warning("Redis auto-start: timed out waiting for readiness")
