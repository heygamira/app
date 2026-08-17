"""Bearer-token verification.

Two verifiers implement the same interface. ``FirebaseVerifier`` is the real
one; ``DevVerifier`` exists so a clean checkout can be exercised without a
Firebase project and is refused outside local/test by ``Settings``.
"""

from __future__ import annotations

import datetime as dt
import time
from dataclasses import dataclass
from typing import Protocol

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
from cryptography.x509 import load_pem_x509_certificate

from app.core.config import Settings
from app.core.errors import Unauthenticated
from app.core.logging import get_logger

logger = get_logger(__name__)

FIREBASE_ISSUER = "https://securetoken.google.com/{project_id}"


@dataclass(frozen=True)
class VerifiedIdentity:
    """The claims the backend is willing to trust from an identity provider."""

    external_auth_id: str
    provider: str
    email: str | None = None
    phone: str | None = None
    display_name: str | None = None
    picture: str | None = None
    email_verified: bool = False


class TokenVerifier(Protocol):
    async def verify(self, token: str) -> VerifiedIdentity: ...


class DevVerifier:
    """Accepts ``dev:<subject>[:email][:display name]`` for local development.

    This is not authentication. It only exists so the API can be driven end to
    end before Firebase is configured, and it is rejected by configuration in
    staging and production.
    """

    def __init__(self, prefix: str = "dev:") -> None:
        self.prefix = prefix

    async def verify(self, token: str) -> VerifiedIdentity:
        if not token.startswith(self.prefix):
            raise Unauthenticated("Local development tokens must start with 'dev:'.")
        parts = token[len(self.prefix) :].split(":")
        subject = parts[0].strip()
        if not subject:
            raise Unauthenticated("Local development token is missing a subject.")
        email = parts[1].strip() if len(parts) > 1 and parts[1].strip() else None
        name = parts[2].strip() if len(parts) > 2 and parts[2].strip() else None
        return VerifiedIdentity(
            external_auth_id=f"dev|{subject}",
            provider="dev",
            email=email,
            display_name=name,
            email_verified=bool(email),
        )


class FirebaseVerifier:
    """Verifies a Firebase ID token against Google's rotating signing keys."""

    def __init__(self, settings: Settings) -> None:
        self.project_id = settings.firebase_project_id
        self.jwks_url = settings.firebase_jwks_url
        self._keys: dict[str, RSAPublicKey] = {}
        self._keys_expire_at: float = 0.0

    async def _signing_key(self, kid: str) -> RSAPublicKey:
        if kid in self._keys and time.time() < self._keys_expire_at:
            return self._keys[kid]
        await self._refresh_keys()
        try:
            return self._keys[kid]
        except KeyError:
            raise Unauthenticated("The token was signed with an unknown key.") from None

    async def _refresh_keys(self) -> None:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(self.jwks_url)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.error("firebase_jwks_fetch_failed", extra={"error": str(exc)})
            raise Unauthenticated("Unable to verify the token right now.") from exc

        # Google publishes x509 certificates keyed by `kid`.
        self._keys = {
            kid: _certificate_public_key(cert) for kid, cert in response.json().items()
        }
        self._keys_expire_at = time.time() + _max_age_seconds(
            response.headers.get("cache-control", "")
        )

    async def verify(self, token: str) -> VerifiedIdentity:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as exc:
            raise Unauthenticated("The bearer token is malformed.") from exc

        kid = header.get("kid")
        if not kid:
            raise Unauthenticated("The bearer token is missing a key id.")

        key = await self._signing_key(kid)
        try:
            claims = jwt.decode(
                token,
                key,
                algorithms=["RS256"],
                audience=self.project_id,
                issuer=FIREBASE_ISSUER.format(project_id=self.project_id),
                options={"require": ["exp", "iat", "sub", "aud", "iss"]},
            )
        except jwt.ExpiredSignatureError as exc:
            raise Unauthenticated("The session has expired. Sign in again.") from exc
        except jwt.PyJWTError as exc:
            raise Unauthenticated("The bearer token is not valid.") from exc

        subject = str(claims.get("sub", "")).strip()
        if not subject:
            raise Unauthenticated("The bearer token has no subject.")
        # auth_time guards against a token minted before a credential change.
        auth_time = claims.get("auth_time")
        if auth_time and auth_time > dt.datetime.now(dt.UTC).timestamp() + 60:
            raise Unauthenticated("The bearer token is not yet valid.")

        firebase = claims.get("firebase", {}) or {}
        return VerifiedIdentity(
            external_auth_id=f"firebase|{subject}",
            provider=str(firebase.get("sign_in_provider", "firebase")),
            email=claims.get("email"),
            phone=claims.get("phone_number"),
            display_name=claims.get("name"),
            picture=claims.get("picture"),
            email_verified=bool(claims.get("email_verified", False)),
        )


def build_verifier(settings: Settings) -> TokenVerifier:
    if settings.auth_mode == "firebase":
        return FirebaseVerifier(settings)
    return DevVerifier(settings.dev_token_prefix)


def _certificate_public_key(certificate_pem: str) -> RSAPublicKey:
    """Extract the RSA public key from one of Google's x509 certificates."""
    certificate = load_pem_x509_certificate(certificate_pem.encode("utf-8"))
    public_key = certificate.public_key()
    if not isinstance(public_key, RSAPublicKey):
        raise Unauthenticated("The token signing key is not usable.")
    return public_key


def _max_age_seconds(cache_control: str, default: int = 3600) -> int:
    for directive in cache_control.split(","):
        directive = directive.strip()
        if directive.startswith("max-age="):
            try:
                return max(60, int(directive.split("=", 1)[1]))
            except ValueError:
                return default
    return default
