"""Read-only installation marker prevents an empty/stale worker consuming live events."""
import json
from pathlib import Path
from .db import CutoverBinding, HistoryBatch


def verify_target(sessions,marker='/migration/marker/state.json'):
    path=Path(marker)
    if not path.exists():return # Fresh isolated pilot, before any legacy cutover.
    state=json.loads(path.read_text())
    if state.get('phase') not in {'activated','released'}:
        raise ValueError('Payments installation is in maintenance or rolled back')
    with sessions() as session:
        binding=session.get(CutoverBinding,'initial')
        batch=session.get(HistoryBatch,'initial')
        if binding is None or batch is None or binding.run_id!=state.get('run_id') or binding.snapshot_sha256!=state.get('snapshot_sha256') or batch.snapshot_hash!=binding.snapshot_sha256:
            raise ValueError('Payments database belongs to a different cutover; startup refused')
