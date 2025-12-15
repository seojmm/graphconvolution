"""Compatibility entrypoint for the MCP service.

The FastAPI app is now unified in `server/app.py`. Use `uvicorn server.app:app`.
"""

from server.app import app

__all__ = ["app"]

