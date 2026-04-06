import asyncio
import time
import httpx
from app import app
import unittest.mock as mock
import os

# Set dummy env vars
os.environ["GITHUB_PAT"] = "dummy"
os.environ["GITHUB_WEBHOOK_SECRET"] = "dummy"

async def main():
    # Add ping endpoint temporarily
    @app.get("/ping")
    async def ping():
        return {"status": "ok"}

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:

        # Mock github_request to sleep for 2 seconds
        with mock.patch("app.github_request") as mock_github:
            mock_response = mock.Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"title": "test", "body": "test"}

            def slow_request(*args, **kwargs):
                print("Slow request started (blocking)")
                time.sleep(2) # Blocking sleep
                print("Slow request finished")
                return mock_response

            mock_github.side_effect = slow_request

            async def call_trigger():
                start = time.perf_counter()
                res = await client.post("/trigger-analyst/1")
                end = time.perf_counter()
                print(f"trigger-analyst finished in {end - start:.4f}s")
                return res

            async def call_ping():
                await asyncio.sleep(0.5) # Wait a bit to ensure trigger started
                print("Ping request started")
                start = time.perf_counter()
                res = await client.get("/ping")
                end = time.perf_counter()
                print(f"ping finished in {end - start:.4f}s")
                return res

            tasks = [call_trigger(), call_ping()]
            await asyncio.gather(*tasks)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        print(f"Error: {e}")
