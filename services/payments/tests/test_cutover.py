from copy import deepcopy
import json
import pytest
from sqlalchemy import select
from payment_service.cutover import check_initial
from payment_service.db import Entry
from payment_service.domain import consume, settle
from payment_service.import_history import import_history
from test_history import history
from test_payments import db, event
from payment_service.target import verify_target


def test_frozen_import_is_verified_without_financial_writes(db):
    _,sessions=db
    source=history()
    empty=check_initial(sessions,source,allow_empty=True)
    assert empty['target_empty']
    import_history(sessions,source)
    result=check_initial(sessions,source)
    assert result['unchanged_since_import'] and not result['target_empty']
    assert result['snapshot_sha256']==empty['snapshot_sha256']


def test_new_work_blocks_rollback_even_when_a_paid_order_is_replayed(db):
    _,sessions=db
    source=history()
    import_history(sessions,source)
    settle(sessions,8001,1,'read-like-write')
    with pytest.raises(ValueError,match='new work'):
        check_initial(sessions,source)


def test_changed_ledger_and_different_snapshot_cannot_pass_reconciliation(db):
    _,sessions=db
    source=history()
    import_history(sessions,source)
    changed=deepcopy(source)
    changed['wallets'][0]['balance_cents']+=1
    with pytest.raises(ValueError,match='different source'):
        check_initial(sessions,changed)
    with sessions.begin() as session:
        session.get(Entry,95).amount_cents+=1
    with pytest.raises(ValueError,match='transaction changed'):
        check_initial(sessions,source)


def test_marker_requires_exact_run_binding_before_api_or_worker_use(db,tmp_path):
    _,sessions=db
    source=history()
    result=import_history(sessions,source)
    marker=tmp_path/'marker.json'
    run='11111111-1111-4111-8111-111111111111'
    manifest={'phase':'activated','run_id':run,'snapshot_sha256':result['snapshot_sha256']}
    marker.write_text(json.dumps(manifest))
    with pytest.raises(ValueError,match='different cutover'):
        verify_target(sessions,marker)
    check_initial(sessions,source,run_id=run,bind=True)
    verify_target(sessions,marker)
    marker.write_text(json.dumps(manifest|{'run_id':'22222222-2222-4222-8222-222222222222'}))
    with pytest.raises(ValueError):verify_target(sessions,marker)
    marker.write_text(json.dumps(manifest|{'phase':'rolled_back'}))
    with pytest.raises(ValueError,match='maintenance or rolled back'):verify_target(sessions,marker)
