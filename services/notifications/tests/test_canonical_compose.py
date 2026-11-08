import importlib.util
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[3]
spec=importlib.util.spec_from_file_location('canonical_compose',ROOT/'scripts/canonical_compose.py')
generator=importlib.util.module_from_spec(spec)
spec.loader.exec_module(generator)


def test_root_bootstrap_is_non_root_network_free_and_has_no_source_mount():
    model=json.loads((ROOT/'docker-compose.yml').read_text())
    bootstrap=model['services']['bootstrap']
    assert bootstrap['network_mode']=='none'
    assert bootstrap['cap_drop']==['ALL']
    assert bootstrap.get('user') not in ('root','0','0:0')
    assert all(mount['type']=='volume' for mount in bootstrap['volumes'])
    assert bootstrap['env_file']==[{'path':'.env.notifications','required':False}]
    dockerfile=(ROOT/'services/notifications/Dockerfile').read_text()
    assert 'USER service' in dockerfile and 'chown service:service /bootstrap' in dockerfile


def test_services_get_only_their_own_read_only_subdirectory():
    model=json.loads((ROOT/'docker-compose.yml').read_text())
    for name in generator.SCOPED:
        service=model['services'][name]
        mount=next(m for m in service['volumes'] if m['source']=='stack-config')
        assert mount['read_only'] and mount['volume']['subpath']==name
        assert not (set(service.get('environment',{})) & generator.PRIVATE_KEYS)
        assert service['depends_on']['bootstrap']['condition']=='service_completed_successfully'
    assert model['services']['edemand']['depends_on']['keycloak-config']['condition']=='service_completed_successfully'
    assert 'profiles' not in model['services']['keycloak-config']
    assert all('name' not in v for v in model['volumes'].values())


def test_generator_rebases_paths_and_removes_private_values():
    model={'services':{name:{'build':{'context':'/source'},
        'environment':{key:'private-test-value' for key in generator.PRIVATE_KEYS},
        'volumes':[{'type':'bind','source':'/source/config','target':'/config'}]} for name in generator.SCOPED},
        'volumes':{'data':{'name':'old-data'}},'networks':{'default':{'name':'old-network'}},
        'x-private-anchor':{'DATABASE_URL':'private-test-value'}}
    result=generator.canonical(model,'/source')
    assert 'private-test-value' not in json.dumps(result)
    assert result['services']['edemand']['build']['context']=='.'
    assert result['services']['edemand']['volumes'][0]['source']=='./config'
