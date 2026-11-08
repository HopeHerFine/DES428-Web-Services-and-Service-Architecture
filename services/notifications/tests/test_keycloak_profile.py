import json

from app.configure_keycloak import managed_identity_profile, PROVISIONER_SCOPES


def test_disabled_unmanaged_policy_is_json_null_not_invalid_enum():
    current = {"attributes": [{"name": "username", "permissions": {"view": ["admin", "user"], "edit": ["admin", "user"]}}],
               "groups": [{"name": "custom-group", "displayHeader": "Custom"}], "unmanagedAttributePolicy": "ADMIN_EDIT"}
    result = managed_identity_profile(current)
    encoded = json.loads(json.dumps(result))
    assert encoded["unmanagedAttributePolicy"] is None
    assert '"DISABLED"' not in json.dumps(result)
    assert result["groups"] == current["groups"]
    assert result["attributes"][0] == current["attributes"][0]
    assert current["unmanagedAttributePolicy"] == "ADMIN_EDIT", "Do not mutate the fetched source object"
    for name in ("role", "legacy_user_id"):
        attribute = next(item for item in result["attributes"] if item["name"] == name)
        assert attribute["permissions"] == {"view": ["admin"], "edit": ["admin"]}
        assert attribute["multivalued"] is False
    assert managed_identity_profile(result) == result, "Rerunning setup must be idempotent"


def test_existing_mapping_validation_and_unrelated_attributes_are_preserved():
    current = {"attributes": [{"name": "legacy_user_id", "validations": {"length": {"max": 32}},
                               "permissions": {"view": ["user"], "edit": ["user"]}},
                              {"name": "department", "displayName": "Department"}]}
    result = managed_identity_profile(current)
    legacy = next(item for item in result["attributes"] if item["name"] == "legacy_user_id")
    assert legacy["validations"]["length"]["max"] == 32
    assert legacy["permissions"]["edit"] == ["admin"]
    assert result["attributes"][1] == current["attributes"][1]


def test_keycloak_2682_admin_scope_is_only_on_the_provisioner():
    from pathlib import Path
    assert set(PROVISIONER_SCOPES) == {"basic", "roles", "kc-admin-api"}
    root = Path(__file__).resolve().parents[3]
    realm = json.loads((root / "keycloak" / "homeservice-realm.json").read_text())
    browser = next(client for client in realm["clients"] if client["clientId"] == "homeservice-web")
    assert "kc-admin-api" not in browser["defaultClientScopes"]
