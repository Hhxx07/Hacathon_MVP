import asyncio
import json

from redis.asyncio import Redis

from .config import get_settings


async def run() -> None:
    redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    try:
        while True:
            item = await redis.blpop("study:jobs", timeout=30)
            if item:
                _, payload = item
                # Dispatch by payload["type"] as handlers are added; never log credentials.
                json.loads(payload)
    finally:
        await redis.aclose()


if __name__ == "__main__":
    asyncio.run(run())

