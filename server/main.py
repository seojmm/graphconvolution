"""FastAPI entrypoint for the Kakao proxy service."""

import uvicorn

from app import app


if __name__ == "__main__":
    uvicorn.run("app:app", reload=True)
