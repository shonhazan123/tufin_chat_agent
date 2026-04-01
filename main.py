"""ASGI entry — re-exports the FastAPI app from `app.main` for `uvicorn main:app`."""

from app.main import app

__all__ = ["app"]
