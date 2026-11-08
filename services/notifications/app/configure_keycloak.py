"""Idempotently attach the standard basic scope to our existing browser client.

Used only by the short-lived configuration container, never by the inbox worker/API.
Existing realms are not replaced and users/passwords are not modified.
"""
import json
import os
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def main():
    base = "http://keycloak:8080/auth"
    password = os.environ["KEYCLOAK_ADMIN_PASSWORD"]
    login = Request(base + "/realms/master/protocol/openid-connect/token", data=urlencode({
        "grant_type": "password", "client_id": "admin-cli", "username": "admin", "password": password,
    }).encode(), headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urlopen(login, timeout=20) as response:
        token = json.load(response)["access_token"]

    def admin(path, method="GET"):
        request = Request(base + "/admin/realms/homeservice" + path, method=method,
                          headers={"Authorization": "Bearer " + token})
        with urlopen(request, timeout=20) as response:
            return json.load(response) if response.status != 204 else None

    clients = admin("/clients?clientId=homeservice-web")
    if len(clients) != 1:
        raise RuntimeError("Expected exactly one homeservice-web client")
    basic = next((scope for scope in admin("/client-scopes") if scope["name"] == "basic"), None)
    if basic is None:
        raise RuntimeError("Keycloak basic scope is missing; inspect realm configuration")
    client_path = "/clients/" + clients[0]["id"] + "/default-client-scopes"
    current = admin(client_path)
    changed = not any(scope["id"] == basic["id"] for scope in current)
    if changed:
        admin(client_path + "/" + basic["id"], "PUT")
    assert any(scope["id"] == basic["id"] for scope in admin(client_path))
    print(json.dumps({"result": "PASS", "configuration": "homeservice-web basic scope",
                      "updated": changed, "users_modified": False}))


if __name__ == "__main__":
    main()
