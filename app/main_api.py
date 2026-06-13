import uvicorn

from app.api import app
from app.config import API_HOST, API_PORT
from app.database import init_db


def main() -> None:
    init_db()

    uvicorn.run(
        app,
        host=API_HOST,
        port=API_PORT,
    )


if __name__ == "__main__":
    main()
