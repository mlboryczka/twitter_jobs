"""HTTP Basic auth dependency — credentials from Settings."""

from __future__ import annotations

import secrets

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from twitter_jobs.config import Settings, get_settings

_basic = HTTPBasic()


def require_basic_auth(
    credentials: HTTPBasicCredentials = Depends(_basic),
    settings: Settings = Depends(get_settings),
) -> str:
    expected_user = settings.dashboard_username
    expected_pass = settings.dashboard_password
    if not expected_user or not expected_pass:
        # Unconfigured — refuse rather than silently allow.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Dashboard credentials not configured",
        )
    user_ok = secrets.compare_digest(credentials.username, expected_user)
    pass_ok = secrets.compare_digest(credentials.password, expected_pass)
    if not (user_ok and pass_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username
