from copy import deepcopy
import pytest
from sqlalchemy import func, select
from sqlalchemy import event as sql_event
from payment_service.db import Base, Entry, HistoryBatch, Outbox, WalletOpening
from payment_service.domain import consume, settle, wallet
from payment_service.import_history import import_history
from test_payments import db, event


def history():
    return {"version":1,"source":"fixture-source","orders":[{
        "order_id":8001,"customer_id":1,"provider_id":1,"amount_cents":107000,
        "commission_cents":10700,"method":"gateway","status":"completed","payment_status":"paid"}],
        "intents":[{"id":1,"order_id":8001,"amount_cents":107000,"gateway_ref":"old-reference",
            "status":"succeeded","created_at":"2026-01-01T00:00:00Z"}],
        "transactions":[{"id":81,"order_id":8001,"customer_id":1,"provider_id":1,"kind":"charge",
            "amount_cents":107000,"method":"gateway","gateway_ref":"old-reference","status":"succeeded","created_at":"2026-01-01T00:00:00Z"},
            {"id":95,"order_id":8001,"customer_id":1,"provider_id":1,"kind":"payout_credit",
            "amount_cents":96300,"method":"gateway","gateway_ref":None,"status":"succeeded","created_at":"2026-01-01T01:00:00Z"}],
        "wallets":[{"provider_id":1,"balance_cents":50000,"commission_owed_cents":1200},
            {"provider_id":2,"balance_cents":3000,"commission_owed_cents":0}]}


def count(sessions, model):
    with sessions() as session:
        return session.scalar(select(func.count()).select_from(model))


def test_history_keeps_exact_wallet_ids_timestamps_and_no_outbound_events(db):
    _,sessions=db
    source=history()
    before=deepcopy(source)
    result=import_history(sessions,source)
    assert source==before
    assert result['wallets_reconciled'] and result['historical_events_emitted']==0
    assert count(sessions,Outbox)==0
    assert wallet(sessions,1)['balance_cents']==50000
    assert wallet(sessions,1)['commission_owed_cents']==1200
    assert wallet(sessions,2)['balance_cents']==3000
    assert [row['id'] for row in wallet(sessions,1)['transactions']]==[95,81]
    assert wallet(sessions,1)['transactions'][0]['created_at'].startswith('2026-01-01T01:00:00')
    with sessions() as session:
        assert session.get(WalletOpening,1).balance_cents==-46300
        assert 'old-reference' in session.get(HistoryBatch,'initial').archive_json


def test_exact_reimport_is_noop_and_changed_source_or_snapshot_is_rejected(db):
    _,sessions=db
    source=history()
    first=import_history(sessions,source)
    assert import_history(sessions,source)==first|{'already_imported':True}
    for changed in (deepcopy(source)|{'source':'other-source'},deepcopy(source)):
        if changed['source']==source['source']:
            changed['wallets'][0]['balance_cents']+=1
        with pytest.raises(ValueError,match='different history'):
            import_history(sessions,changed)
    assert count(sessions,Entry)==2
    assert wallet(sessions,1)['balance_cents']==50000


@pytest.mark.parametrize('problem',['ownership','duplicate','amount','missing_intent'])
def test_inconsistent_history_has_no_partial_import(db,problem):
    _,sessions=db
    source=history()
    if problem=='ownership':source['transactions'][1]['provider_id']=2
    elif problem=='duplicate':source['transactions'].append(dict(source['transactions'][1],id=99))
    elif problem=='amount':source['transactions'][1]['amount_cents']=1
    else:source['intents']=[]
    with pytest.raises(ValueError):import_history(sessions,source)
    assert count(sessions,Entry)==0
    assert count(sessions,HistoryBatch)==0
    assert count(sessions,WalletOpening)==0


def test_nonempty_target_is_not_overwritten(db):
    _,sessions=db
    consume(sessions,event(order=9001))
    with pytest.raises(ValueError,match='unused Payments'):
        import_history(sessions,history())
    assert count(sessions,HistoryBatch)==0


def test_new_payments_after_import_keep_opening_balance_and_sequence(db):
    _,sessions=db
    source=history()
    import_history(sessions,source)
    consume(sessions,event('completed')) # Historical completion cannot credit twice.
    assert wallet(sessions,1)['balance_cents']==50000
    consume(sessions,event('created',order=8002))
    settle(sessions,8002,1,'new-payment')
    consume(sessions,event('completed',order=8002))
    result=wallet(sessions,1)
    assert result['balance_cents']==146300
    assert result['transactions'][0]['id']>95
    assert import_history(sessions,source)['already_imported']
    assert wallet(sessions,1)['balance_cents']==146300


def test_failure_after_ledger_inserts_rolls_back_the_entire_batch(db):
    engine,sessions=db
    def fail_batch(connection,cursor,statement,parameters,context,executemany):
        if statement.lstrip().upper().startswith('INSERT INTO HISTORY_IMPORTS'):
            raise RuntimeError('injected import commit failure')
    sql_event.listen(engine,'before_cursor_execute',fail_batch)
    try:
        with pytest.raises(RuntimeError,match='injected'):
            import_history(sessions,history())
    finally:
        sql_event.remove(engine,'before_cursor_execute',fail_batch)
    assert count(sessions,Entry)==0
    assert count(sessions,WalletOpening)==0
    assert count(sessions,HistoryBatch)==0
    assert import_history(sessions,history())['result']=='PASS'
