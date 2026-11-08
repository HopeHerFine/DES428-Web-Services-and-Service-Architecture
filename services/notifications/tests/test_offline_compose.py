import importlib.util
from pathlib import Path
import pytest

spec=importlib.util.spec_from_file_location('offline_compose',Path(__file__).resolve().parents[3]/'scripts/offline_compose.py')
offline=importlib.util.module_from_spec(spec)
spec.loader.exec_module(offline)


def model():
    return {'services':{name:{'image':'vendor/demo:1','build':{'context':'/clean'},
        'profiles':['migration'],'volumes':[{'type':'bind','source':'/clean/config/demo','target':'/config'}]}
        for name in offline.LIMITS},'volumes':{'database':{'name':'original-database'}}}


def test_frozen_boot_uses_prepared_images_internal_network_and_fresh_volumes():
    source=model()
    result=offline.freeze(source,'test-only','/clean','prepared-app:1','prepared-api:1')
    assert result['networks']['default']['internal'] is True
    assert 'name' not in result['volumes']['database']
    assert source['volumes']['database']['name']=='original-database'
    assert result['services']['edemand']['image']=='prepared-app:1'
    assert result['services']['notifications-worker']['image']=='prepared-api:1'
    for service in result['services'].values():
        assert 'build' not in service and 'profiles' not in service
        assert service['pull_policy']=='never'
        assert service['volumes'][0]['source']=='./config/demo'
        assert service['mem_limit']==service['memswap_limit']
    assert result['services']['edemand']['depends_on']['keycloak-config']['condition']=='service_completed_successfully'


def test_offline_test_never_mounts_original_sources_or_external_volumes():
    source=model()
    source['services']['edemand']['volumes'][0]['source']='/original/private'
    with pytest.raises(ValueError,match='escaped'):
        offline.freeze(source,'test','/clean','app','api')
    source=model()
    source['volumes']['database']['external']=True
    with pytest.raises(ValueError,match='External'):
        offline.freeze(source,'test','/clean','app','api')


def test_windows_paths_are_rebased_and_memory_caps_fit_eight_gib():
    source=model()
    for service in source['services'].values():
        service['volumes'][0]['source']='C:\\Clean\\config\\demo'
    result=offline.freeze(source,'test','C:\\Clean','app','api')
    assert result['services']['edemand']['volumes'][0]['source']=='./config/demo'
    assert sum(int(size[:-1]) for size in offline.LIMITS.values()) < 8*1024
