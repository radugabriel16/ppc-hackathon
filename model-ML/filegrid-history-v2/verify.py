"""Checks the generated SQLite artifact, including outage/consumption consistency."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import sqlite3


def verify(folder):
    folder=Path(folder)
    manifest=json.loads((folder/'manifest.json').read_text())
    checks=[]
    with sqlite3.connect(f'file:{folder / "history.sqlite"}?mode=ro', uri=True) as db:
        def scalar(sql):
            return db.execute(sql).fetchone()[0]
        assert scalar('SELECT count(*) FROM regiuni')==3
        assert scalar('SELECT count(*) FROM segmente')==18
        assert scalar('SELECT count(*) FROM contoare')==126
        assert not db.execute('SELECT region_id FROM segmente GROUP BY region_id HAVING count(*)!=6').fetchall()
        assert not db.execute('SELECT segment_id FROM contoare GROUP BY segment_id HAVING count(*)!=7').fetchall()
        checks.append('3 regions, 18 segments, exactly 7 meters per segment')
        assert scalar('SELECT count(*) FROM stats_contor')==manifest['days']*126*4
        assert not db.execute('SELECT meter_id,substr(interval_start,1,10) FROM stats_contor GROUP BY 1,2 HAVING count(*)!=4').fetchall()
        assert scalar('SELECT count(*) FROM stats_contor WHERE energy_kwh<0')==0
        for start,end in db.execute('SELECT interval_start,interval_end FROM stats_contor'):
            assert (datetime.fromisoformat(end)-datetime.fromisoformat(start)).total_seconds()==21600
        checks.append('complete 4-per-day history, 6-hour intervals, no negative energy')
        assert scalar('SELECT count(*) FROM stats_avarii')==manifest['outages']
        assert scalar('SELECT count(*) FROM avarii_video')==0
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
        assert scalar('''SELECT count(*) FROM avarii_contoare ac
                         JOIN stats_avarii a ON a.id=ac.incident_id
                         JOIN contoare m ON m.id=ac.meter_id
                         WHERE a.segment_id!=m.segment_id''')==0
        checks.append('incident/meter foreign keys and segment association; no fake video records')
        full_overlap='''SELECT r.reading_key, r.energy_kwh FROM stats_contor r
                        JOIN avarii_contoare ac ON ac.meter_id=r.meter_id
                        JOIN stats_avarii a ON a.id=ac.incident_id
                        WHERE r.interval_start>=a.occurred_at AND r.interval_end<=a.restored_at'''
        full=db.execute(full_overlap).fetchall()
        assert all(energy==0 for _,energy in full)
        zero_count=scalar('SELECT count(*) FROM stats_contor WHERE energy_kwh=0')
        assert zero_count==len({key for key,_ in full})
        checks.append('all zero-energy intervals correspond to a full simulated interruption')
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        checks.append('SQLite integrity_check: ok')
    return dict(status='PASS', checks=checks, verifiedReadings=manifest['readings'],
                verifiedOutages=manifest['outages'],fullyInterruptedReadings=len(full),
                postgresExecuted=False,modelsExecuted=False)


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--data',required=True)
    a=p.parse_args()
    report=verify(a.data)
    (Path(a.data)/'verification.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2))
