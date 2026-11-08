"""Disposable Pact provider. Never import into the production app.

Uses the real FastAPI routes/repository and a temporary database. Identity token
verification alone is stubbed: JWT/Keycloak behavior has separate security tests.
"""
import os
import tempfile
from datetime import datetime
from fastapi import Request
from sqlalchemy import delete
from app.db import Base, Notification, ProcessedEvent, WriteReceipt, database
from app.main import create_app
from app.settings import Settings

scratch = tempfile.TemporaryDirectory(prefix='notifications-pact-')
url = os.getenv('PACT_DATABASE_URL', 'sqlite:///' + scratch.name.replace('\\','/') + '/provider.db')
engine, sessions = database(url)
Base.metadata.create_all(engine)


def verify(token):
    if token not in {'pact-customer', 'pact-other'}:
        raise ValueError('invalid contract identity')
    return {'role':'customer','legacy_user_id':'1' if token == 'pact-customer' else '2'}


app = create_app(Settings(url,'unused','notifications','unused',''),engine,sessions,verify)


@app.post('/_pact/state')
async def state(request: Request):
    name = (await request.json())['state']
    if name not in {'customer has unread notification','empty inbox'}:
        raise ValueError('unknown provider state')
    with sessions.begin() as session:
        session.execute(delete(WriteReceipt))
        session.execute(delete(Notification))
        session.execute(delete(ProcessedEvent))
        if name == 'customer has unread notification':
            session.add(Notification(id=41,event_id='pact-event',recipient_role='customer',recipient_id='1',
                type='rating_request',title='How did it go?',body='Booking #8001 is complete',order_id=8001,
                created_at=datetime(2026,1,1)))
    return {'state':name}
