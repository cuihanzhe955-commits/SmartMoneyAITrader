"""Historical catch-up changes pacing only; never eligibility or persistence."""
from unittest.mock import patch
import pytest
from terminal.runtime import Runtime
from terminal.config import Session

@pytest.mark.parametrize('mode', ['due','future','paused','ai','normal_speed','public','remote'])
def test_catchup_is_only_for_due_historical_rule_paper(tmp_path,mode):
    rt=Runtime(tmp_path)
    try:
        s=rt.new(Session(consent=True,speed=3600))
        s.update(lifecycle_status='RUNNING',next_scan=s['start'])
        if mode=='future':s['next_scan']=s['start']+60
        if mode=='paused':s['lifecycle_status']='PAUSED'
        if mode=='ai':s['engine_override']='ai'
        if mode=='normal_speed':s['config']['speed']=1
        if mode=='public':s['config']['source']='public'
        if mode=='remote':s['config']['execution']='live'
        with rt.db.db:rt.db.save(s)
        with patch('terminal.runtime.market_time',return_value=s['start']):
            assert rt.replay_delay(.04)==(.001 if mode=='due' else .04)
        assert rt.db.load()==s
        assert rt.db.db.execute('PRAGMA synchronous').fetchone()[0]==2
    finally:rt.shutdown();rt.db.db.close()
