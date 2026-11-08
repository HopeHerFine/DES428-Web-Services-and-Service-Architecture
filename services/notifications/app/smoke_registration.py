"""Register both roles, sign in through real Keycloak, then receive an approval notification."""
import http.cookiejar
import json
import secrets
import time
from uuid import uuid4
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, build_opener

from .smoke_gateway import browser_login, request, GatewayHTTPHandler, LocalhostBrowserCookiePolicy


def main():
    anonymous = build_opener(GatewayHTTPHandler(), HTTPCookieProcessor(
        http.cookiejar.CookieJar(policy=LocalhostBrowserCookiePolicy())))
    created = {}
    for role in ("customer", "provider"):
        email = f"registration-{role}-{uuid4()}@example.com"
        password = "Demo-" + secrets.token_urlsafe(18)
        account = request(anonymous, f"/api/auth/{role}/register", {
            "email": email, "password": password, "name": f"New {role} integration probe",
        })
        client = browser_login(email, password)
        me = request(client, "/api/me")
        assert me["role"] == role and me["id"] == account["id"] and me["email"] == email
        assert request(client, "/api/notifications") == [], "New account unexpectedly inherited another inbox"
        try:
            request(anonymous, f"/api/auth/{role}/register", {
                "email": email, "password": password, "name": "Duplicate registration",
            })
        except HTTPError as error:
            assert error.code == 409
        else:
            raise AssertionError("Active account was registered again")
        created[role] = {"id": account["id"], "client": client}
    admin = browser_login("admin@edemand.test")
    provider_id = created["provider"]["id"]
    approved = request(admin, f"/api/admin/providers/{provider_id}/approve", {})
    assert approved["is_approved"]
    deadline = time.monotonic() + 60
    while True:
        inbox = request(created["provider"]["client"], "/api/notifications")
        approval = next((row for row in inbox if row["type"] == "provider_approved"), None)
        if approval:
            break
        if time.monotonic() > deadline:
            raise RuntimeError("New provider did not receive its approval notification")
        time.sleep(1)
    read = request(created["provider"]["client"], f"/api/notifications/{approval['id']}/read", {})
    assert read["read_at"] is not None
    try:
        request(created["customer"]["client"], f"/api/notifications/{approval['id']}/read", {})
    except HTTPError as error:
        assert error.code == 403
    else:
        raise AssertionError("New customer could change the provider's notification")
    print(json.dumps({"result": "PASS", "flow": "new registration -> Keycloak login -> own inbox",
                      "customer_id": created["customer"]["id"], "provider_id": provider_id,
                      "notification_id": approval["id"], "duplicate_rejection": 409,
                      "ownership_rejection": 403, "passwords_logged": False}))


if __name__ == "__main__":
    main()
