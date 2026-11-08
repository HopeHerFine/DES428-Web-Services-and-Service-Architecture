"""Live Keycloak security checks; temporary clients are removed in finally.

Only this short-lived test container receives the admin password. Browser login
keeps authorization-code+PKCE and never enables direct grants on homeservice-web.
"""
import json
import os
import time
from datetime import datetime, timezone
from uuid import uuid4
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import jwt

BASE = os.getenv("KEYCLOAK_SETUP_BASE", "http://keycloak:8080/auth")
GATEWAY = os.getenv("SECURITY_GATEWAY_BASE", "http://gateway")


def send(url, method="GET", data=None, headers=None):
    with urlopen(Request(url, method=method, data=data, headers=headers or {}), timeout=15) as response:
        raw = response.read()
        return json.loads(raw) if raw else None


def token(client_id, username, password, realm="homeservice"):
    return send(f"{BASE}/realms/{realm}/protocol/openid-connect/token", "POST",
                urlencode({"grant_type": "password", "client_id": client_id,
                           "username": username, "password": password}).encode(),
                {"Content-Type": "application/x-www-form-urlencoded"})["access_token"]


def check(name, expected, bearer=None, origin=None, method="GET"):
    correlation = "security-" + str(uuid4())
    headers = {"X-Request-Id": correlation, "Host": "localhost:8080"}
    if bearer:
        headers["Authorization"] = "Bearer " + bearer
    if origin:
        headers["Origin"] = origin
    request = Request(GATEWAY + "/api/notifications", method=method, headers=headers)
    try:
        with urlopen(request, timeout=15) as response:
            actual = response.status
            returned_id = response.headers.get("X-Request-Id")
    except HTTPError as error:
        actual = error.code
        returned_id = error.headers.get("X-Request-Id")
    assert actual == expected, f"{name}: expected {expected}, received {actual}"
    assert returned_id == correlation, f"{name}: gateway lost correlation ID"
    return {"case": name, "expected": expected, "actual": actual, "correlation_id": correlation}


def main():
    admin_token = token("admin-cli", "admin", os.environ["KEYCLOAK_ADMIN_PASSWORD"], "master")

    def admin(path, method="GET", body=None):
        data = json.dumps(body).encode() if body is not None else None
        return send(BASE + "/admin/realms/homeservice" + path, method, data,
                    {"Authorization": "Bearer " + admin_token, "Content-Type": "application/json"})

    browser = admin("/clients?clientId=homeservice-web")
    assert len(browser) == 1 and not browser[0].get("directAccessGrantsEnabled", False)
    assert browser[0].get("attributes", {}).get("pkce.code.challenge.method") == "S256"
    source_mappers = admin("/clients/" + browser[0]["id"] + "/protocol-mappers/models")
    scopes = {scope["name"]: scope["id"] for scope in admin("/client-scopes")}
    created = []
    checks = []
    try:
        client_ids = []
        for audience in ("notifications", "unrelated-service"):
            client_id = "security-probe-" + str(uuid4())
            mappers = []
            for original in source_mappers:
                mapper = {key: value for key, value in original.items() if key != "id"}
                mapper["config"] = dict(mapper.get("config", {}))
                if mapper["protocolMapper"] == "oidc-audience-mapper":
                    mapper["config"]["included.custom.audience"] = audience
                mappers.append(mapper)
            admin("/clients", "POST", {"clientId": client_id, "enabled": True, "protocol": "openid-connect",
                  "publicClient": True, "standardFlowEnabled": False, "directAccessGrantsEnabled": True,
                  "attributes": {"access.token.lifespan": "5"}, "protocolMappers": mappers})
            representation = admin("/clients?clientId=" + client_id)[0]
            created.append(representation["id"])
            for name in ("basic", "profile", "email"):
                admin("/clients/" + representation["id"] + "/default-client-scopes/" + scopes[name], "PUT")
            client_ids.append(client_id)
        checks.append(check("missing_token", 401))
        checks.append(check("forged_token", 401, "forged.invalid.token"))
        bad_audience = token(client_ids[1], "sparkle@example.com", "eDemand-2026!")
        # Decode only for a test precondition, never to authenticate a request.
        bad_claims = jwt.decode(bad_audience, options={"verify_signature": False})
        audiences = bad_claims.get("aud", [])
        if isinstance(audiences, str):
            audiences = [audiences]
        assert "notifications" not in audiences and "unrelated-service" in audiences
        checks.append(check("wrong_audience", 401, bad_audience))
        good = token(client_ids[0], "sparkle@example.com", "eDemand-2026!")
        checks.append(check("valid_keycloak_token", 200, good))
        checks.append(check("cross_origin_write", 403, good, "https://untrusted.example", "POST"))
        claims = jwt.decode(good, options={"verify_signature": False})
        remaining = claims["exp"] - time.time()
        assert remaining <= 10, "Temporary client's short token lifespan was not applied"
        while time.time() <= claims["exp"] + 1:
            time.sleep(0.25)
        checks.append(check("expired_keycloak_token", 401, good))
    finally:
        for identifier in reversed(created):
            admin("/clients/" + identifier, "DELETE")
    print(json.dumps({"result": "PASS", "probe": "keycloak-gateway-security",
                      "recorded_at": datetime.now(timezone.utc).isoformat(),
                      "checks": checks, "temporary_clients_removed": True,
                      "browser_pkce_preserved": True}))


if __name__ == "__main__":
    main()
