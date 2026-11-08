from dataclasses import dataclass
import jwt
from jwt import PyJWKClient
from fastapi import HTTPException, Request


@dataclass(frozen=True)
class Principal:
    role: str
    user_id: int


def verifier(issuer, jwks):
    keys = PyJWKClient(jwks, timeout=5)
    def verify(token):
        key = keys.get_signing_key_from_jwt(token).key
        return jwt.decode(token, key, algorithms=["RS256"], issuer=issuer, audience="payments",
            options={"require": ["exp", "sub", "iss", "aud"]})
    return verify


def authenticated(request: Request):
    header = request.headers.get("authorization", "")
    if not header.startswith("Bearer "):
        raise HTTPException(401, "Missing bearer token", headers={"WWW-Authenticate": "Bearer"})
    try:
        claims = request.app.state.verify(header[7:])
    except (jwt.PyJWTError, ValueError):
        raise HTTPException(401, "Invalid bearer token", headers={"WWW-Authenticate": "Bearer"}) from None
    role, user_id = claims.get("role"), str(claims.get("legacy_user_id", ""))
    if role not in {"customer", "provider"} or not user_id.isdecimal() or int(user_id) <= 0:
        raise HTTPException(403, "Account mapping missing")
    return Principal(role, int(user_id))
