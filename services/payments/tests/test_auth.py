from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from payment_service.auth import authenticated, verifier


def test_payments_verifier_rejects_bad_tokens(monkeypatch):
    issuer = "https://issuer.example/realms/homeservice"
    signing_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setattr(jwt.PyJWKClient, "get_signing_key_from_jwt",
                        lambda self, token: SimpleNamespace(key=signing_key.public_key()))

    app = FastAPI()
    app.state.verify = verifier(issuer, issuer + "/protocol/openid-connect/certs")

    @app.get("/wallet")
    def wallet(principal=Depends(authenticated)):
        return {"user_id": principal.user_id}

    now = datetime.now(timezone.utc)
    claims = {"iss": issuer, "sub": "provider-subject", "aud": "payments",
              "exp": now + timedelta(minutes=5), "role": "provider", "legacy_user_id": "1"}
    with TestClient(app) as client:
        def call(payload, key=signing_key):
            token = jwt.encode(payload, key, algorithm="RS256")
            return client.get("/wallet", headers={"Authorization": f"Bearer {token}"})

        valid = call(claims)
        assert valid.status_code == 200
        assert valid.json() == {"user_id": 1}
        for response in (
            call(claims, other_key),
            call({**claims, "exp": now - timedelta(minutes=1)}),
            call({**claims, "aud": "notifications"}),
        ):
            assert response.status_code == 401
            assert response.headers["WWW-Authenticate"] == "Bearer"
