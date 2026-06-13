import asyncio

from app.runtime import run_polling_and_api_runtime


if __name__ == "__main__":
    asyncio.run(run_polling_and_api_runtime())
