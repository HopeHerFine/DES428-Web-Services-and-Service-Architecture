"""Idempotently attach the standard basic scope to our existing browser client.

Used only by the short-lived configuration container, never by the inbox worker/API.
Existing realms are not replaced and users/passwords are not modified.
"""
import json
import os
from copy import deepcopy
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

PROVISIONER_SCOPES = ("basic", "roles", "kc-admin-api")

def managed_identity_profile(current):
    profile = deepcopy(current)
    for name in ("role", "legacy_user_id"):
        attribute = next((item for item in profile["attributes"] if item["name"] == name), None)
        if attribute is None:
            attribute = {"name": name, "multivalued": False}
            profile["attributes"].append(attribute)
        attribute["permissions"] = {"view": ["admin"], "edit": ["admin"]}
        attribute["multivalued"] = False
        attribute.setdefault("displayName", "Account role" if name == "role" else "Homeservice account ID")
        attribute.setdefault("validations", {}).setdefault("length", {"max": 64})
    # Keycloak 26.8.2's enum accepts ENABLED/ADMIN_VIEW/ADMIN_EDIT only.
    # Disabled is represented by null, not the invalid string "DISABLED".
    profile["unmanagedAttributePolicy"] = None
    return profile


def main():
    base = os.getenv("KEYCLOAK_SETUP_BASE", "http://keycloak:8080/auth")
    password = os.environ["KEYCLOAK_ADMIN_PASSWORD"]
    login = Request(base + "/realms/master/protocol/openid-connect/token", data=urlencode({
        "grant_type": "password", "client_id": "admin-cli", "username": "admin", "password": password,
    }).encode(), headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urlopen(login, timeout=20) as response:
        token = json.load(response)["access_token"]

    def admin(path, method="GET", body=None):
        request = Request(base + "/admin/realms/homeservice" + path, method=method,
                          data=json.dumps(body).encode() if body is not None else None,
                          headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
        try:
            with urlopen(request, timeout=20) as response:
                raw = response.read()
                return json.loads(raw) if raw else None
        except HTTPError as error:
            # Only the profile endpoint's validation response is safe to display.
            # Never print request bodies/headers or responses from token/client APIs.
            if path == "/users/profile":
                raw = error.read(8192).decode(errors="replace")
                try:
                    details = json.loads(raw)
                except ValueError:
                    details = {"message": "Non-JSON profile validation error"}
                raise RuntimeError(json.dumps({"stage": "keycloak_user_profile",
                                               "http_status": error.code,
                                               "validation": details})) from None
            raise

    clients = admin("/clients?clientId=homeservice-web")
    if len(clients) != 1:
        raise RuntimeError("Expected exactly one homeservice-web client")
    # Existing realms are preserved: add only the new Payments audience mapper.
    mapper_path = "/clients/" + clients[0]["id"] + "/protocol-mappers/models"
    mappers = admin(mapper_path)
    if not any(mapper.get("config", {}).get("included.custom.audience") == "payments" for mapper in mappers):
        admin(mapper_path, "POST", {"name": "payments audience", "protocol": "openid-connect",
            "protocolMapper": "oidc-audience-mapper", "config": {
                "included.custom.audience": "payments", "access.token.claim": "true", "id.token.claim": "false"}})
    basic = next((scope for scope in admin("/client-scopes") if scope["name"] == "basic"), None)
    if basic is None:
        raise RuntimeError("Keycloak basic scope is missing; inspect realm configuration")
    client_path = "/clients/" + clients[0]["id"] + "/default-client-scopes"
    current = admin(client_path)
    changed = not any(scope["id"] == basic["id"] for scope in current)
    if changed:
        admin(client_path + "/" + basic["id"], "PUT")
    assert any(scope["id"] == basic["id"] for scope in admin(client_path))
    secret = os.environ["PROVISIONER_CLIENT_SECRET"]
    provisioners = admin("/clients?clientId=homeservice-provisioner")
    provisioner = {"clientId": "homeservice-provisioner", "enabled": True, "protocol": "openid-connect",
                   "publicClient": False, "serviceAccountsEnabled": True, "standardFlowEnabled": False,
                   "directAccessGrantsEnabled": False, "fullScopeAllowed": False, "secret": secret}
    if not provisioners:
        admin("/clients", "POST", provisioner)
    else:
        admin("/clients/" + provisioners[0]["id"], "PUT", {**provisioners[0], **provisioner})
    provisioner_id = admin("/clients?clientId=homeservice-provisioner")[0]["id"]
    service_user = admin("/clients/" + provisioner_id + "/service-account-user")
    management = admin("/clients?clientId=realm-management")[0]["id"]
    manage_users = admin("/clients/" + management + "/roles/manage-users")
    admin("/users/" + service_user["id"] + "/role-mappings/clients/" + management, "POST", [manage_users])
    # Service-account roles and client role scopes are intersected in the token.
    # Assigning manage-users alone is insufficient when the roles mapper/scope
    # is absent. Scope this client to that one management role explicitly.
    admin("/clients/" + provisioner_id + "/scope-mappings/clients/" + management, "POST", [manage_users])
    scope_ids = {scope["name"]: scope["id"] for scope in admin("/client-scopes")}
    for name in PROVISIONER_SCOPES:
        admin("/clients/" + provisioner_id + "/default-client-scopes/" + scope_ids[name], "PUT")
    profile = managed_identity_profile(admin("/users/profile"))
    admin("/users/profile", "PUT", profile)
    saved = admin("/users/profile")
    assert saved.get("unmanagedAttributePolicy") is None, "Unmanaged attributes must remain disabled"
    for name in ("role", "legacy_user_id"):
        attribute = next(item for item in saved["attributes"] if item["name"] == name)
        assert attribute["permissions"] == {"view": ["admin"], "edit": ["admin"]}
    service_login = Request(base + "/realms/homeservice/protocol/openid-connect/token",
                            data=urlencode({"grant_type": "client_credentials", "client_id": "homeservice-provisioner",
                                            "client_secret": secret}).encode(),
                            headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urlopen(service_login, timeout=20) as response:
            service_token = json.load(response)["access_token"]
        permission_check = Request(base + "/admin/realms/homeservice/users?max=1",
                                   headers={"Authorization": "Bearer " + service_token})
        with urlopen(permission_check, timeout=20) as response:
            assert response.status == 200
    except HTTPError as error:
        raise RuntimeError(json.dumps({"stage": "provisioner_permission_check", "http_status": error.code})) from None
    print(json.dumps({"result": "PASS", "configuration": "homeservice-web basic scope",
                      "updated": changed, "users_modified": False, "registration_provisioner_ready": True}))


if __name__ == "__main__":
    main()
