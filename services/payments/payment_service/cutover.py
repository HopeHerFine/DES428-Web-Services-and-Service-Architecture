"""Read-only reconciliation of a never-released initial history import."""
import argparse
import json
import os
from pathlib import Path
import re
from sqlalchemy import func, select, text
from .db import Base, Entry, HistoryBatch, Intent, Outbox, Receipt, WalletOpening, CutoverBinding, database
from .domain import fingerprint
from .import_history import History, timestamp, validate, import_history


def lock(session):
    if session.bind.dialect.name=='postgresql':
        session.execute(text('LOCK TABLE payment_intents, transactions, processed_events, outbox, wallet_openings, history_imports, cutover_binding IN EXCLUSIVE MODE'))


def verify(session, document, allow_empty=False):
    digest=fingerprint(document)
    batch=session.get(HistoryBatch,'initial')
    models=(Intent,Entry,WalletOpening,Receipt,Outbox,CutoverBinding)
    if batch is None:
        if allow_empty and not any(session.scalar(select(func.count()).select_from(model)) for model in models):
            return {'result':'PASS','snapshot_sha256':digest,'unchanged_since_import':True,'target_empty':True}
        raise ValueError('No matching import exists, or the target is not empty')
    history=History.model_validate(document)
    intents=validate(history)
    if batch.snapshot_hash!=fingerprint(history.model_dump()) or batch.snapshot_hash!=digest:
        raise ValueError('Target contains a different source snapshot')
    if session.scalar(select(func.count()).select_from(Receipt)) or session.scalar(select(func.count()).select_from(Outbox)):
        raise ValueError('Payments received new work; rollback is forbidden')
    rows=session.scalars(select(Intent)).all()
    if len(rows)!=len(history.orders):raise ValueError('Payments booking set changed')
    by_id={row.order_id:row for row in rows}
    for old in history.orders:
        row=by_id.get(old.order_id)
        if row is None or any(getattr(row,key)!=value for key,value in old.model_dump(exclude={'status','payment_status'}).items()):
            raise ValueError('Imported commercial snapshot changed')
        expected=('refunded' if old.payment_status=='refunded' else 'succeeded' if old.payment_status=='paid'
            else 'cancelled' if old.status=='cancelled' else intents[old.order_id].status if old.order_id in intents else 'requires_payment')
        if (row.status,row.completed,row.cancelled)!=(expected,old.status=='completed',old.status=='cancelled'):
            raise ValueError('Imported payment state changed')
    entries=session.scalars(select(Entry)).all()
    if len(entries)!=len(history.transactions):raise ValueError('Financial ledger changed')
    by_id={row.id:row for row in entries}
    for old in history.transactions:
        row=by_id.get(old.id)
        if row is None or any(getattr(row,key)!=value for key,value in old.model_dump(exclude={'gateway_ref','created_at'}).items()):
            raise ValueError('Historical transaction changed')
        actual=row.created_at
        if actual.tzinfo is None:actual=timestamp(actual.isoformat())
        if actual!=timestamp(old.created_at):raise ValueError('Historical timestamp changed')
    openings=session.scalars(select(WalletOpening)).all()
    if len(openings)!=len(history.wallets):raise ValueError('Wallet set changed')
    by_id={row.provider_id:row for row in openings}
    for old in history.wallets:
        opening=by_id.get(old.provider_id)
        rows=[row for row in entries if row.provider_id==old.provider_id and row.status=='succeeded']
        if opening is None or opening.balance_cents+sum(row.amount_cents for row in rows if row.kind=='payout_credit')!=old.balance_cents or opening.commission_cents+sum(row.amount_cents for row in rows if row.kind=='commission_owed')!=old.commission_owed_cents:
            raise ValueError('Authoritative wallet balance changed')
    return {'result':'PASS','snapshot_sha256':digest,'unchanged_since_import':True,'target_empty':False}


def check_initial(sessions,document,allow_empty=False,run_id=None,bind=False):
    with sessions.begin() as session:
        lock(session)
        proof=verify(session,document,allow_empty)
        if run_id and not proof['target_empty']:
            old=session.get(CutoverBinding,'initial')
            if old is None and bind:
                session.add(CutoverBinding(id='initial',run_id=run_id,snapshot_sha256=proof['snapshot_sha256']))
            elif old is None or old.run_id!=run_id or old.snapshot_sha256!=proof['snapshot_sha256']:
                raise ValueError('Different cutover target binding; keep maintenance closed')
        return proof


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=['preflight','import','check'])
    parser.add_argument('--run-id')
    args=parser.parse_args()
    engine,sessions=database(os.environ['DATABASE_URL'])
    Base.metadata.create_all(engine)
    try:
        if args.action=='preflight':
            with sessions.begin() as session:
                lock(session)
                if any(session.scalar(select(func.count()).select_from(model)) for model in (Intent,Entry,WalletOpening,Receipt,Outbox,HistoryBatch,CutoverBinding)):
                    raise ValueError('Payments target must be unused before a new cutover')
            print(json.dumps({'result':'PASS','target_empty':True}))
            return
        if not args.run_id or not re.fullmatch('[a-f0-9-]{36}',args.run_id):raise ValueError('Valid run ID required')
        document=json.loads(Path('/migration/source',args.run_id,'history.json').read_text())
        if args.action=='import':import_history(sessions,document)
        result=check_initial(sessions,document,allow_empty=args.action=='check',run_id=args.run_id,bind=args.action=='import')
        if args.action=='import' and result['target_empty']:raise ValueError('Import was not committed')
        result['run_id']=args.run_id
        Path('/migration/report',args.run_id+'-check.json').write_text(json.dumps(result),encoding='utf-8')
        print(json.dumps(result))
    finally:engine.dispose()


if __name__=='__main__':main()
