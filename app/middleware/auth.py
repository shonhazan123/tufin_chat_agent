"""API key verification for protected routes."""

from __future__ import annotations

import secrets

from fastapi import Depends, Header, HTTPException, status

from app.settings import Settings, get_settings


async def verify_api_key( x_api_key: str | None = Header(None, alias="X-API-Key"), settings: Settings = Depends(get_settings)) -> None:
    expected = settings.api_key
    if not expected:
        return
    if x_api_key is None or not secrets.compare_digest(x_api_key, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
        )
