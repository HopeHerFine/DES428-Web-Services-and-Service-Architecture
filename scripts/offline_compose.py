"""Freeze a prepared Compose model into an image-only, isolated demo stack."""
import argparse
from copy import deepcopy
import json
from pathlib import Path

LIMITS = {'keycloak':'896m','gateway':'128m','edemand':'1024m','notifications-db':'512m',
          'rabbitmq':'768m','notifications':'512m','notifications-worker':'384m',
          'jaeger':'512m','prometheus':'384m','grafana':'384m','keycloak-config':'384m'}
PYTHON_SERVICES = {'notifications','notifications-worker','keycloak-config','bootstrap'}


def freeze(model, project, source_root, app_image, api_image):
    model = deepcopy(model)
    prefix = source_root.replace('\\','/').rstrip('/') + '/'
    services = {}
    limits={**LIMITS,**({'bootstrap':'256m'} if 'bootstrap' in model['services'] else {})}
    for name in limits:
        service = model['services'][name]
        service.pop('build',None)
        service.pop('profiles',None)
        if name in PYTHON_SERVICES:
            service['image'] = api_image
        elif name == 'edemand':
            service['image'] = app_image
        if not service.get('image'):
            raise ValueError('Missing prepared image: ' + name)
        service['pull_policy'] = 'never'
        service['mem_limit'] = limits[name]
        service['memswap_limit'] = limits[name]
        for mount in service.get('volumes',[]):
            if mount['type'] == 'bind':
                source = mount['source'].replace('\\','/')
                if not source.casefold().startswith(prefix.casefold()):
                    raise ValueError('Bind mount escaped clean source: ' + name)
                mount['source'] = './' + source[len(prefix):]
        services[name] = service
    services['keycloak-config'].setdefault('depends_on',{})['keycloak'] = {'condition':'service_healthy'}
    services['edemand'].setdefault('depends_on',{})['keycloak-config'] = {'condition':'service_completed_successfully'}
    # Skip optional online update checks in the local offline demonstration.
    services['grafana'].setdefault('environment',{}).update({
        'GF_ANALYTICS_CHECK_FOR_UPDATES':'false','GF_ANALYTICS_CHECK_FOR_PLUGIN_UPDATES':'false',
        'GF_ANALYTICS_REPORTING_ENABLED':'false'})
    volumes = deepcopy(model.get('volumes',{}))
    for volume in volumes.values():
        if volume.get('external'):
            raise ValueError('External volumes are not permitted in a cold-start test')
        volume.pop('name',None)
    return {'name':project,'services':services,'volumes':volumes,
            'networks':{'default':{'internal':True}}}


def main():
    parser=argparse.ArgumentParser()
    for name in ('input','output','project','source-root','app-image','api-image'):
        parser.add_argument('--'+name,required=True)
    args=parser.parse_args()
    model=json.loads(Path(args.input).read_text(encoding='utf-8-sig'))
    result=freeze(model,args.project,args.source_root,args.app_image,args.api_image)
    # The resolved file contains newly generated local credentials. Keep it in
    # the ignored test directory; never publish it with the source repository.
    Path(args.output).write_text(json.dumps(result,indent=2),encoding='utf-8')
    print('Prepared image-only offline Compose stack; credentials were not printed.')


if __name__=='__main__':
    main()
