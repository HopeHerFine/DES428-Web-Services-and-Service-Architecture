from dataclasses import dataclass

import jwt
from fastapi import HTTPException, Request
from jwt import PyJWKClient


@dataclass(frozen=True)
class Principal:
    role: str
    user_id: str


def build_verifier(settings):
    keys = PyJWKClient(settings.jwks_url, timeout=5)

    def verify(token):
        key = keys.get_signing_key_from_jwt(token).key
        return jwt.decode(
            token, key, algorithms=["RS256"], audience=settings.audience,
            issuer=settings.issuer, options={"require": ["exp", "sub", "iss", "aud"]},
        )

    return verify


def authenticated(request: Request):
    header = request.headers.get("authorization", "")
    if not header.startswith("Bearer "):
        raise HTTPException(401, "missing bearer token", headers={"WWW-Authenticate": "Bearer"})
    try:
        claims = request.app.state.verify_token(header[7:])
    except (jwt.PyJWTError, ValueError):
        raise HTTPException(401, "invalid token", headers={"WWW-Authenticate": "Bearer"})
    # Keycloak must map these two claims from the existing user account. Never accept
    # ownership IDs from request headers/query parameters or from the client's body.
    role = claims.get("role")
    user_id = claims.get("legacy_user_id")
    if role not in {"customer", "provider", "admin"} or user_id is None:
        raise HTTPException(403, "account mapping missing")
    return Principal(role, str(user_id))
