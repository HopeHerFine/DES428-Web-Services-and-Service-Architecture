"""Generate canonical Compose from the existing operator-service model."""
import argparse
from copy import deepcopy
import json
from pathlib import Path

SCOPED={'legacy-export','notifications-db','rabbitmq','keycloak','edemand','notifications',
        'notifications-worker','keycloak-config','security-probe','resilience-fixture','broker-recovery'}
PRIVATE_KEYS={'DATABASE_URL','RABBITMQ_URL','POSTGRES_PASSWORD','RABBITMQ_DEFAULT_PASS','KC_BOOTSTRAP_ADMIN_PASSWORD',
              'JWT_SECRET','KEYCLOAK_ADMIN_PASSWORD','PROVISIONER_CLIENT_SECRET','LEGACY_SOURCE_ID'}
DEFAULT_COMMANDS={'edemand':['node','server.js'],'notifications-db':['postgres'],'rabbitmq':['rabbitmq-server'],
    'notifications':['uvicorn','app.main:create_app','--factory','--host','0.0.0.0','--port','8000','--log-level','info']}
ORIGINAL_ENTRIES={'keycloak':['/opt/keycloak/bin/kc.sh'],'notifications-db':['docker-entrypoint.sh'],
                  'rabbitmq':['docker-entrypoint.sh'],'legacy-export':['node','/app/export-legacy-notifications.mjs']}


def canonical(model,source_root):
    model=deepcopy(model)
    # Resolved Compose preserves extension anchors too. They can still contain
    # private connection strings even after service environments are sanitized.
    for key in list(model):
        if key.startswith('x-'):
            model.pop(key)
    prefix=source_root.replace('\\','/').rstrip('/')+'/'
    def relative(path):
        normalized=path.replace('\\','/')
        if normalized.rstrip('/').casefold()==prefix.rstrip('/').casefold():
            return '.'
        if not normalized.casefold().startswith(prefix.casefold()):
            raise ValueError('Configuration path escaped repository root')
        return './'+normalized[len(prefix):]
    model['name']='homeservice-notifications'
    for name,service in model['services'].items():
        if 'build' in service:
            service['build']['context']=relative(service['build']['context'])
        for mount in service.get('volumes',[]):
            if mount['type']=='bind':
                mount['source']=relative(mount['source'])
                if mount['source'] in ('./runtime/faults','./runtime/probes'):
                    mount.setdefault('bind',{})['create_host_path']=True
        if name not in SCOPED:
            continue
        environment=service.get('environment',{})
        for key in PRIVATE_KEYS:
            environment.pop(key,None)
        service['environment']=environment
        service['entrypoint']=['/bin/sh','/run/local-env/launch.sh',*ORIGINAL_ENTRIES.get(name,[])]
        if name in DEFAULT_COMMANDS:
            service['command']=DEFAULT_COMMANDS[name]
        service.setdefault('volumes',[]).append({'type':'volume','source':'stack-config',
            'target':'/run/local-env','read_only':True,'volume':{'subpath':name,'nocopy':True}})
        service.setdefault('depends_on',{})['bootstrap']={'condition':'service_completed_successfully'}
    model['services']['bootstrap']={
        'build':{'context':'./services/notifications'},
        'command':['python','-m','app.bootstrap_stack'],
        'env_file':[{'path':'.env.notifications','required':False}],
        'network_mode':'none','cap_drop':['ALL'],'security_opt':['no-new-privileges:true'],
        'volumes':[{'type':'volume','source':'stack-config','target':'/bootstrap'}],
    }
    setup=model['services']['keycloak-config']
    setup.pop('profiles',None)
    setup['depends_on']['keycloak']={'condition':'service_healthy'}
    model['services']['edemand']['depends_on']['keycloak-config']={'condition':'service_completed_successfully'}
    model.setdefault('volumes',{})['stack-config']={}
    for volume in model['volumes'].values():
        if volume.get('external'):
            raise ValueError('External volumes require explicit review')
        volume.pop('name',None)
    for network in model.get('networks',{}).values():
        network.pop('name',None)
    return model


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--input',required=True)
    parser.add_argument('--output',required=True)
    parser.add_argument('--source-root',required=True)
    args=parser.parse_args()
    source=json.loads(Path(args.input).read_text(encoding='utf-8-sig'))
    Path(args.output).write_text(json.dumps(canonical(source,args.source_root),indent=2)+'\n',encoding='utf-8')
    print('Generated canonical Compose without inline credentials or a required environment file.')

