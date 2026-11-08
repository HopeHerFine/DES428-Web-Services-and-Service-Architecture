import json
import pytest
from app.bootstrap_stack import prepare,SECRET_KEYS,service_environments


def test_fresh_boot_generates_persistent_random_settings_without_source_files(tmp_path):
    result=prepare(tmp_path,{})
    settings=json.loads((tmp_path/'settings.json').read_text())
    assert result['generated_secret_values']==len(SECRET_KEYS)
    assert len({settings[name] for name in SECRET_KEYS})==len(SECRET_KEYS)
    assert all(len(settings[name])==48 for name in SECRET_KEYS)
    assert not any(value in json.dumps(result) for name,value in settings.items())
    before=(tmp_path/'settings.json').read_bytes()
    assert prepare(tmp_path,{})['generated_secret_values']==0
    assert (tmp_path/'settings.json').read_bytes()==before
    assert (tmp_path/'notifications'/'launch.sh').read_bytes().count(b'\r')==0


def test_existing_credentials_are_adopted_without_rotation(tmp_path):
    supplied={name:'existing-'+name for name in SECRET_KEYS}
    assert prepare(tmp_path,supplied)['generated_secret_values']==0
    assert all(json.loads((tmp_path/'settings.json').read_text())[name]==value for name,value in supplied.items())
    before=(tmp_path/'settings.json').read_bytes()
    with pytest.raises(RuntimeError,match='changed'):
        prepare(tmp_path,{**supplied,'JWT_SECRET':'different'})
    assert (tmp_path/'settings.json').read_bytes()==before


def test_api_scope_does_not_receive_identity_admin_or_broker_credentials(tmp_path):
    prepare(tmp_path,{})
    settings=json.loads((tmp_path/'settings.json').read_text())
    values=service_environments(settings)
    assert set(values['notifications'])=={'DATABASE_URL'}
    assert set(values['edemand'])=={'JWT_SECRET','PROVISIONER_CLIENT_SECRET','RABBITMQ_URL'}
    api=(tmp_path/'notifications'/'environment').read_text()
    assert settings['KEYCLOAK_ADMIN_PASSWORD'] not in api
    assert settings['RABBITMQ_PASSWORD'] not in api
    assert settings['JWT_SECRET'] not in api


def test_shell_and_connection_string_values_are_encoded_safely(tmp_path):
    settings={name:'a quote\' $value:@/?#' for name in SECRET_KEYS}
    prepare(tmp_path,settings)
    db=service_environments(settings)['notifications']['DATABASE_URL']
    assert '%27' in db and '%40' in db
    assert ' $value' not in db
    with pytest.raises(ValueError,match='line breaks'):
        prepare(tmp_path/'invalid',{'JWT_SECRET':'one\ntwo'})
