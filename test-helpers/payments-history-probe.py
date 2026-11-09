"""Destructive reset is confined to this explicitly disposable fixture database."""
import json
import os
from pathlib import Path
from sqlalchemy import func, select
from payment_service.db import Base, Entry, Outbox, database
from payment_service.domain import Event, consume, settle, wallet
from payment_service.import_history import import_history

engine,sessions=database(os.environ['DATABASE_URL'])
if engine.url.database!='payments_history_fixture' or os.environ.get('HISTORY_FIXTURE')!='synthetic':
    raise RuntimeError('Only the disposable history fixture database may be reset')
Base.metadata.drop_all(engine)
Base.metadata.create_all(engine)
document=json.loads(Path('/history/payment-history.json').read_text())
first=import_history(sessions,document)
assert first['wallets_reconciled'] and not first['already_imported']
assert import_history(sessions,document)==first|{'already_imported':True}
for old in document['wallets']:
    current=wallet(sessions,old['provider_id'])
    assert current['balance_cents']==old['balance_cents']
    assert current['commission_owed_cents']==old['commission_owed_cents']
with sessions() as session:
    assert session.scalar(select(func.count()).select_from(Outbox))==0
    assert session.get(Entry,95).created_at.isoformat().startswith('2026-01-01T01:00:00')
before=wallet(sessions,1)
settle(sessions,8001,1,'already-paid-history')
assert wallet(sessions,1)==before
settle(sessions,8003,1,'pay-old-pending')
consume(sessions,Event(id='fixture-complete-pending',type='billing.booking_completed',payload={
    'order_id':8003,'customer_id':1,'provider_id':1,'amount_cents':21400,'commission_cents':3210,'method':'gateway'}))
assert wallet(sessions,1)['balance_cents']==68190
assert wallet(sessions,1)['transactions'][0]['id']>96
assert import_history(sessions,document)['already_imported']
assert wallet(sessions,1)['balance_cents']==68190
print(json.dumps(first|{'probe':'synthetic-payments-history','reimport_preserved_new_payments':True,
    'pending_legacy_payment_settled':True,'source_application_untouched':True}))
engine.dispose()
