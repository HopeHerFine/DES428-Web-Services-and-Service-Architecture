import copy
from datetime import datetime
import pytest
from sqlalchemy import select, func
from app.db import Base, Notification, database
from app.import_legacy import import_rows


@pytest.fixture
def storage(tmp_path):
    engine, sessions = database(f"sqlite:///{tmp_path / 'history.db'}")
    Base.metadata.create_all(engine)
    yield sessions
    engine.dispose()


def export():
    return {'version':1,'source':'stable-deployment-id','rows':[
        {'id':1,'recipient_role':'customer','recipient_id':1,'type':'booking_status',
         'title':'แจ้งเตือนเก่า','body':'ทดสอบภาษาไทย','order_id':8001,'read_at':None,'created_at':'2026-01-01T00:00:00Z'},
        {'id':2,'recipient_role':'provider','recipient_id':1,'type':'payment_received',
         'title':'Payment','body':'Paid','order_id':None,'read_at':'2026-01-02T00:00:00Z','created_at':'2026-01-01T00:00:00Z'}]}


def test_import_preserves_ownership_timestamps_and_unicode(storage):
    source = export()
    before = copy.deepcopy(source)
    assert import_rows(storage,source)['imported'] == 2
    assert source == before
    with storage() as session:
        rows = session.scalars(select(Notification).order_by(Notification.id)).all()
        assert [(r.recipient_role,r.recipient_id) for r in rows] == [('customer','1'),('provider','1')]
        assert rows[0].title == 'แจ้งเตือนเก่า'
        assert rows[0].read_at is None and rows[1].read_at is not None
        assert rows[1].order_id is None


def test_replay_never_duplicates_or_reverts_newer_read_state(storage):
    source = export()
    import_rows(storage,source)
    with storage.begin() as session:
        row = session.scalar(select(Notification).where(Notification.recipient_role == 'customer'))
        row.read_at = datetime(2026,2,1)
    result = import_rows(storage,source)
    assert result['imported'] == 0 and result['already_imported'] == 2
    with storage() as session:
        assert session.scalar(select(func.count()).select_from(Notification)) == 2
        row = session.scalar(select(Notification).where(Notification.recipient_role == 'customer'))
        assert row.read_at == datetime(2026,2,1)


def test_invalid_export_is_rejected_before_any_write(storage):
    source = export()
    source['rows'][1]['recipient_role'] = 'unknown'
    with pytest.raises(ValueError):
        import_rows(storage,source)
    with storage() as session:
        assert session.scalar(select(func.count()).select_from(Notification)) == 0


def test_duplicate_source_ids_are_rejected(storage):
    source = export()
    source['rows'][1]['id'] = 1
    with pytest.raises(ValueError, match='Duplicate legacy IDs'):
        import_rows(storage,source)
