"""Non-root, network-free initialization of a dedicated local configuration volume.

The bootstrap container sees the whole configuration volume. Other containers
receive read-only mounts of only their own subdirectory. No source bind is used.
"""
import hashlib
import json
import os
from pathlib import Path
import secrets
import shlex
from urllib.parse import quote

SECRET_KEYS=('NOTIFICATIONS_DB_PASSWORD','RABBITMQ_PASSWORD','JWT_SECRET',
             'KEYCLOAK_ADMIN_PASSWORD','PROVISIONER_CLIENT_SECRET','LEGACY_SOURCE_ID','PAYMENTS_DB_PASSWORD')
PUBLIC_DEFAULTS={
    'JWT_ISSUER':'http://localhost:8080/auth/realms/homeservice',
    'JWT_JWKS_URL':'http://keycloak:8080/auth/realms/homeservice/protocol/openid-connect/certs',
}
LAUNCH='#!/bin/sh\nset -a\n. /run/local-env/environment\nset +a\nexec "$@"\n'


def service_environments(settings):
    db='postgresql+psycopg://notifications:'+quote(settings['NOTIFICATIONS_DB_PASSWORD'],safe='')+'@notifications-db:5432/notifications'
    broker='amqp://notifications:'+quote(settings['RABBITMQ_PASSWORD'],safe='')+'@rabbitmq:5672/%2F'
    delivery={'DATABASE_URL':db,'RABBITMQ_URL':broker}
    payments_db='postgresql+psycopg://payments:'+quote(settings['PAYMENTS_DB_PASSWORD'],safe='')+'@payments-db:5432/payments'
    return {
        'notifications-db':{'POSTGRES_PASSWORD':settings['NOTIFICATIONS_DB_PASSWORD']},
        'rabbitmq':{'RABBITMQ_DEFAULT_PASS':settings['RABBITMQ_PASSWORD']},
        'keycloak':{'KC_BOOTSTRAP_ADMIN_PASSWORD':settings['KEYCLOAK_ADMIN_PASSWORD']},
        'edemand':{'JWT_SECRET':settings['JWT_SECRET'],'PROVISIONER_CLIENT_SECRET':settings['PROVISIONER_CLIENT_SECRET'],'RABBITMQ_URL':broker},
        'notifications':{'DATABASE_URL':db},
        'notifications-worker':delivery,
        'keycloak-config':{name:settings[name] for name in ('KEYCLOAK_ADMIN_PASSWORD','PROVISIONER_CLIENT_SECRET')},
        'security-probe':{'KEYCLOAK_ADMIN_PASSWORD':settings['KEYCLOAK_ADMIN_PASSWORD']},
        'resilience-fixture':delivery,
        'broker-recovery':delivery,
        'legacy-export':{'LEGACY_SOURCE_ID':settings['LEGACY_SOURCE_ID']},
        'payments-db':{'POSTGRES_PASSWORD':settings['PAYMENTS_DB_PASSWORD']},
        'payments':{'DATABASE_URL':payments_db},
        'payments-worker':{'DATABASE_URL':payments_db,'RABBITMQ_URL':broker},
    }


def atomic_write(path,text,mode):
    temporary=path.with_name(path.name+'.tmp-'+secrets.token_hex(8))
    try:
        temporary.write_text(text,encoding='utf-8',newline='\n')
        temporary.chmod(mode)
        if path.exists():
            path.chmod(0o600)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def prepare(directory,environment):
    directory=Path(directory)
    directory.mkdir(parents=True,exist_ok=True)
    if directory.is_symlink():
        raise RuntimeError('Configuration volume must not be a symlink')
    directory.chmod(0o700)
    state_path=directory/'settings.json'
    previous=json.loads(state_path.read_text()) if state_path.exists() else None
    settings=dict(previous or {})
    generated=0
    for name in SECRET_KEYS:
        supplied=environment.get(name,'')
        if supplied and previous and supplied!=previous.get(name):
            raise RuntimeError('Local credentials changed after initialization; restore the existing settings before restarting.')
        if supplied:
            settings[name]=supplied
        elif not settings.get(name):
            settings[name]=secrets.token_hex(24)
            generated+=1
    for name,value in PUBLIC_DEFAULTS.items():
        settings.setdefault(name,environment.get(name) or value)
    if any('\n' in value or '\r' in value for value in settings.values()):
        raise ValueError('Local setting values cannot contain line breaks')
    if settings != previous:
        atomic_write(state_path,json.dumps(settings),0o600)
    for name,values in service_environments(settings).items():
        target=directory/name
        if target.is_symlink():
            raise RuntimeError('Service environment must not be a symlink')
        target.mkdir(exist_ok=True)
        target.chmod(0o755)
        atomic_write(target/'environment',''.join(key+'='+shlex.quote(value)+'\n' for key,value in values.items()),0o444)
        atomic_write(target/'launch.sh',LAUNCH,0o555)
    return {'result':'PASS','probe':'stack-bootstrap','generated_secret_values':generated,
            'service_environments':len(service_environments(settings)),'existing_values_preserved':True}


if __name__=='__main__':
    print(json.dumps(prepare('/bootstrap',os.environ)))
