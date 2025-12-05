"""FastAPI entrypoint, following the official `main:app` pattern."""

from server.app import app

# To run locally: `uv run uvicorn main:app --reload --env-file .env.local`
