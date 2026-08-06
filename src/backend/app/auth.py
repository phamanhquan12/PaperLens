"""Supabase JWT authentication with guest-trial and local-development fallbacks."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient

from app.config import Settings, get_settings
from app.guest import GuestQuotaSnapshot, resolve_guest_token


_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class CurrentUser:
    user_id: str
    email: str | None = None
    is_guest: bool = False
    guest_quota: GuestQuotaSnapshot | None = None


@lru_cache(maxsize=4)
def _jwk_client(url: str) -> PyJWKClient:
    return PyJWKClient(url, cache_keys=True, lifespan=300)


def _unauthorized(message: str = "Authentication required") -> HTTPException:
    return HTTPException(
        status_code=401,
        detail=message,
        headers={"WWW-Authenticate": "Bearer"},
    )


def current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    settings: Settings = Depends(get_settings),
) -> CurrentUser:
    """Verify a Supabase or guest access token and return its account identity."""
    if not settings.auth_enabled:
        return CurrentUser(user_id="local-user", email=None, is_guest=False)
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _unauthorized()

    token = credentials.credentials
    guest = resolve_guest_token(token, settings=settings)
    if guest is not None:
        user_id, quota = guest
        return CurrentUser(
            user_id=user_id,
            email=None,
            is_guest=True,
            guest_quota=quota,
        )

    issuer = settings.supabase_jwt_issuer
    if not issuer and settings.supabase_auth_url:
        issuer = f"{settings.supabase_auth_url.rstrip('/')}/auth/v1"
    options = {"require": ["exp", "sub"]}
    kwargs = {
        "algorithms": ["HS256", "RS256", "ES256"],
        "audience": settings.supabase_jwt_audience,
        "issuer": issuer,
        "options": options,
    }
    try:
        if settings.supabase_jwt_secret:
            claims = jwt.decode(token, settings.supabase_jwt_secret, **kwargs)
        elif settings.supabase_jwks_url or settings.supabase_auth_url:
            jwks_url = settings.supabase_jwks_url or (
                f"{settings.supabase_auth_url.rstrip('/')}"
                "/auth/v1/.well-known/jwks.json"
            )
            signing_key = _jwk_client(jwks_url).get_signing_key_from_jwt(token)
            claims = jwt.decode(token, signing_key.key, **kwargs)
        else:
            raise _unauthorized("Authentication is enabled but Supabase Auth is not configured")
    except HTTPException:
        raise
    except jwt.PyJWTError as exc:
        raise _unauthorized("Invalid or expired access token") from exc

    user_id = str(claims.get("sub") or "").strip()
    if not user_id:
        raise _unauthorized("Access token has no account identity")
    return CurrentUser(user_id=user_id, email=claims.get("email"), is_guest=False)
