"""Two fresh Windows service processes reuse isolated F-format databases."""
import json
import sqlite3
import subprocess
import sys
import threading
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient
from terminal.api import create_app
from challenge.prediction import PredictionChallenges
from events.lab import EventLab
from test_event_lab import lab as make_f, enqueue
from test_prediction_challenge import system


WINDOWS = ('RESERVED', 'QUEUED', 'FETCHING', 'PREDICTING', 'WAITING', 'SETTLED', 'STOPPING', 'REFUNDED')


def history(root, sid):
    with sqlite3.connect(root / 'terminal.db') as db:
        return [db.execute(query, (sid,)).fetchall() for query in (
            'SELECT * FROM event_lab_sessions WHERE id=?',
            'SELECT * FROM event_lab_rounds WHERE session_id=? ORDER BY id',
            'SELECT c.* FROM event_lab_cash c JOIN event_lab_rounds r ON r.id=c.round_id WHERE r.session_id=? ORDER BY kind')]


def checkpoint(manager, lab, cid, clock, model, window):
    if window == 'RESERVED':
        with patch.object(manager, '_dispatch', side_effect=InterruptedError):
            try:
                manager.tick()
            finally:
                assert manager.view(cid)['challenges'][0]['rounds'][0]['round_id'] is None
        return
    manager.tick()
    row = manager.view(cid)['challenges'][0]['rounds'][0]
    if window == 'FETCHING':
        with lab.brain.db(True) as db:
            db.execute("UPDATE event_lab_rounds SET status='FETCHING' WHERE id=?", (row['round_id'],))
    elif window == 'PREDICTING':
        model.chat.side_effect = KeyboardInterrupt()
        try:
            lab.tick('work')
        except KeyboardInterrupt:
            pass
    elif window != 'QUEUED':
        lab.tick('work')
        if window == 'STOPPING':
            manager.command(cid, 'stop')
        elif window in ('SETTLED', 'REFUNDED'):
            clock[0] += 61 if window == 'SETTLED' else 0
            lab.tick('settle')
    expected = {'STOPPING': 'WAITING', 'REFUNDED': 'FAILED'}.get(window, window)
    with lab.brain.db() as db:
        assert db.execute('SELECT status FROM event_lab_rounds WHERE id=?', (row['round_id'],)).fetchone()[0] == expected


def run_phase(root, phase, window):
    metadata = root / 'fixture.json'
    if phase == 'seed':
        root.mkdir()
        f, sid, clock, _, _ = make_f(root)
        enqueue(f, sid)
        f.tick(); clock[0] += 100; f.tick(); f.tick('work')
        with f.brain.db(True) as db:
            assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='prediction_challenges'").fetchone()
            # F predates G1's condition guard and both cash snapshot fields.
            db.execute("""UPDATE event_lab_rounds SET
                inputs=json_remove(inputs,'$.expected_condition_id'),
                data=json_remove(data,'$.reference_cash_after_entry','$.reference_cash_after_settlement')
                WHERE session_id=?""", (sid,))
        legacy = history(root, sid)
        assert len(legacy[2]) == 2
    else:
        sid, cid, legacy = json.loads(metadata.read_text())
    # Use the production FastAPI lifespan and Runtime. Drive worker ticks manually
    # so each subprocess stops at the requested transaction boundary.
    fixture = root / 'sources'
    fixture.mkdir(exist_ok=True)
    source_dir = fixture / phase
    source_dir.mkdir()
    source, sample_lab, _, clock, model, config = system(source_dir, rounds=1)
    app = create_app(root)
    def controlled(method):
        def tick(self, *args):
            if threading.current_thread() is threading.main_thread():
                return method(self, *args)
        return tick
    with patch.object(EventLab, 'tick', controlled(EventLab.tick)), patch.object(
            PredictionChallenges, 'tick', controlled(PredictionChallenges.tick)), TestClient(app) as api:
        assert api.get('/api/health').status_code == 200
        lab = app.state.event_lab
        manager = lab.challenges
        lab.clock = manager.clock = lambda: clock[0]
        lab.provider_factory = lambda: model
        lab.details.cost = sample_lab.details.cost
        lab.details.resolution = sample_lab.details.resolution
        manager.discovery.run = source.discovery.run
        if phase == 'seed':
            cid = manager.create(config.model_copy(update={'request_id': str(uuid4())}))['id']
            checkpoint(manager, lab, cid, clock, model, window)
            metadata.write_text(json.dumps([sid, cid, legacy]))
        else:
            for _ in range(3):
                manager.tick()
                lab.tick('work')
                clock[0] += 61
                lab.tick('settle')
                manager.tick()
            final = manager.view(cid)['challenges'][0]
            assert final['status'] == {'STOPPING': 'STOPPED', 'REFUNDED': 'PAUSED'}.get(window, 'COMPLETED'), (window, final)
            assert len(final['rounds']) == 1
            assert lab.reconcile(final['session_id'])['verified']
            with lab.brain.db() as db:
                rows = db.execute('SELECT id FROM event_lab_rounds WHERE session_id=?', (final['session_id'],)).fetchall()
                assert len(rows) == 1
                kinds = sorted(r[0] for r in db.execute('SELECT kind FROM event_lab_cash WHERE round_id=?', (rows[0][0],)))
                assert kinds == ['DEBIT', 'REFUND' if window == 'REFUNDED' else 'PAYOUT']
        assert json.dumps(legacy) == json.dumps(history(root, sid))


def test_two_process_service_recovery(tmp_path):
    for phase in ('seed', 'restore'):
        subprocess.run([sys.executable, '-X', 'utf8', '-B', __file__, phase, str(tmp_path)],
                       check=True, cwd=ROOT, timeout=120)


if __name__ == '__main__':
    from run_offline import guard
    sys.addaudithook(guard)
    for case in WINDOWS:
        run_phase(Path(sys.argv[2]) / case, sys.argv[1], case)

