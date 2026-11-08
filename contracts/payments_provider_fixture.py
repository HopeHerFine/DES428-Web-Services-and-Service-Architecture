"""Disposable Payments Pact fixture; never copied into the production image.

The real service, database and ownership checks run. Only JWT verification is
substituted; real Keycloak behavior is covered separately by security/live tests.
"""
import os
import tempfile
from fastapi import Request
from sqlalchemy import delete
from payment_service.db import Base, Entry, Intent, Outbox, Receipt, database
from payment_service.domain import Event, consume, settle
from payment_service.main import create_app

scratch=tempfile.TemporaryDirectory(prefix='payments-pact-')
url=os.getenv('PACT_PAYMENTS_DATABASE_URL','sqlite:///'+scratch.name.replace('\\','/')+'/provider.db')
engine,sessions=database(url)
Base.metadata.create_all(engine)


def verify(token):
    identities={'pact-customer':('customer','1'),'pact-other':('customer','2'),'pact-provider':('provider','1')}
    if token not in identities:
        raise ValueError('invalid contract identity')
    role,user=identities[token]
    return {'role':role,'legacy_user_id':user}


app=create_app(engine,sessions,verify)


@app.post('/_pact/state')
async def state(request: Request):
    name=(await request.json())['state']
    if name not in {'payable booking','settled booking','settled completed booking'}:
        raise ValueError('Unknown Payments provider state')
    with sessions.begin() as session:
        for table in (Outbox,Receipt,Entry,Intent):
            session.execute(delete(table))
    payload={'order_id':8001,'customer_id':1,'provider_id':1,'amount_cents':107000,
             'commission_cents':10700,'method':'gateway'}
    consume(sessions,Event(id='pact-created',type='billing.booking_created',payload=payload))
    if name!='payable booking':
        settle(sessions,8001,1,'pact-seed-settlement')
    if name=='settled completed booking':
        consume(sessions,Event(id='pact-completed',type='billing.booking_completed',payload=payload))
    return {'state':name}
