"""Shared FastAPI dependencies."""

from __future__ import annotations

import functools
from typing import Annotated

from fastapi import Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.errors import Unauthenticated
from app.core.security import TokenVerifier, build_verifier
from app.db.session import get_session
from app.models.identity import User
from app.services.identity import get_or_create_user

SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


@functools.lru_cache(maxsize=1)
def _verifier() -> TokenVerifier:
    return build_verifier(get_settings())


def get_verifier(request: Request) -> TokenVerifier:
    """Allow tests and startup to override the verifier through app state."""
    override = getattr(request.app.state, "token_verifier", None)
    if override is not None:
        return override  # type: ignore[no-any-return]
    return _verifier()


async def get_current_user(
    session: SessionDep,
    verifier: Annotated[TokenVerifier, Depends(get_verifier)],
    authorization: Annotated[str | None, Header()] = None,
) -> User:
    """Resolve the caller from a bearer token, provisioning on first sight."""
    if not authorization:
        raise Unauthenticated("An Authorization header is required.")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise Unauthenticated("Use 'Authorization: Bearer <token>'.")

    identity = await verifier.verify(token.strip())
    return await get_or_create_user(session, identity)


CurrentUser = Annotated[User, Depends(get_current_user)]


async def get_idempotency_key(
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> str | None:
    return idempotency_key.strip()[:128] if idempotency_key else None


IdempotencyKey = Annotated[str | None, Depends(get_idempotency_key)]
