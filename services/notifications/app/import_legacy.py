"""Append historical inbox rows without changing source data or newer read state."""
import hashlib
import json
import sys
import argparse
from pathlib import Path
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field
from sqlalchemy import select
from .db import Base, Notification, ProcessedEvent, database
from .settings import Settings


class LegacyRow(BaseModel):
    id: int = Field(gt=0)
    recipient_role: Literal['customer','provider','admin']
    recipient_id: int = Field(gt=0)
    type: str = Field(min_length=1,max_length=64)
    title: str = Field(max_length=256)
    body: str
    order_id: int | None
    read_at: datetime | None
    created_at: datetime


def import_rows(sessions, document):
    if document.get('version') != 1 or not isinstance(document.get('source'), str) or not document['source']:
        raise ValueError('Invalid export version/source')
    rows = [LegacyRow.model_validate(row) for row in document['rows']]
    if len({row.id for row in rows}) != len(rows):
        raise ValueError('Duplicate legacy IDs in export')
    added = skipped = 0
    with sessions.begin() as session:
        for row in rows:
            event_id = 'legacy:' + hashlib.sha256(f"{document['source']}:{row.id}".encode()).hexdigest()
            if session.get(ProcessedEvent,event_id):
                existing = session.scalar(select(Notification).where(Notification.event_id == event_id))
                if existing is None:
                    raise RuntimeError('Legacy receipt exists without its notification')
                skipped += 1
                continue
            session.add(ProcessedEvent(id=event_id))
            session.add(Notification(event_id=event_id,recipient_role=row.recipient_role,
                recipient_id=str(row.recipient_id),type=row.type,title=row.title,body=row.body,
                order_id=row.order_id,read_at=row.read_at,created_at=row.created_at))
            added += 1
    return {'result':'PASS','probe':'legacy-notifications-import','source_rows':len(rows),
            'imported':added,'already_imported':skipped,'source_unchanged':True}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--file')
    parser.add_argument('--report')
    args = parser.parse_args()
    document = json.loads(Path(args.file).read_text(encoding='utf-8-sig') if args.file else
                          sys.stdin.buffer.read().decode('utf-8-sig'))
    engine, sessions = database(Settings.from_env().database_url)
    try:
        Base.metadata.create_all(engine)
        result = import_rows(sessions,document)
        if args.report:
            with open(args.report, 'x', encoding='utf-8') as report:
                json.dump(result, report)
        print(json.dumps(result))
    finally:
        engine.dispose()


if __name__ == '__main__':
    main()
