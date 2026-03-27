import asyncio
import time
from app import lifespan, app

async def measure_blocking():
    start_time = time.perf_counter()
    async with lifespan(app):
        pass
    end_time = time.perf_counter()
    print(f"Lifespan execution time: {end_time - start_time:.4f} seconds")

if __name__ == "__main__":
    asyncio.run(measure_blocking())
