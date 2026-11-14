"""FileGrid history v2: standard library only, no models, no video files."""
import argparse
from collections import deque
import csv
from datetime import date, datetime, timedelta, timezone
import json
import math
from pathlib import Path
import random
import sqlite3
from uuid import NAMESPACE_URL, uuid5

UTC = timezone.utc


def uid(key):
    return str(uuid5(NAMESPACE_URL, 'filegrid-history-v2/' + key))


def iso(t):
    return t.isoformat().replace('+00:00', 'Z') if t else None


def generate(out, seed=42, start='2024-11-14', end='2026-11-14'):
    out = Path(out)
    if (out/'history.sqlite').exists():
        raise FileExistsError('Refusing to replace existing history.sqlite; choose a new --out directory')
    out.mkdir(parents=True, exist_ok=True)
    begin, finish = [datetime.combine(date.fromisoformat(d), datetime.min.time(), UTC) for d in (start, end)]
    days = (finish-begin).days
    if days < 1:
        raise ValueError('end must be later than start')
    rng = random.Random(seed)
    tables = {}
    tables['regiuni'] = [dict(id=uid(code), code=code) for code in ('MUNTENIA','BANAT','DOBROGEA')]
    segments, meters = [], []
    for r, region in enumerate(tables['regiuni']):
        for s in range(6):
            n = r*6+s
            segments.append(dict(id=uid(f'segment-{n}'), region_id=region['id'], code=f'SEG-{n+1:03}'))
            for j in range(7):
                number = n*7+j
                kind = rng.choices(['RESIDENTIAL','COMMERCIAL','INDUSTRIAL'], [8,1.5,.5])[0]
                profile = rng.choices(['LOW','NORMAL','HIGH'], [.15,.70,.15])[0]
                factor = {'LOW':(.3,.6),'NORMAL':(.8,1.3),'HIGH':(2,4)}[profile]
                base = {'RESIDENTIAL':(5,12),'COMMERCIAL':(35,90),'INDUSTRIAL':(150,400)}[kind]
                meters.append(dict(id=uid(f'meter-{number}'), external_code=f'M-{number+1:03}',
                                   segment_id=segments[-1]['id'], client_type=kind,
                                   consumption_profile=profile,
                                   demo_base_daily_kwh=round(rng.uniform(*base)*rng.uniform(*factor),6)))
    tables['segmente'], tables['contoare'] = segments, meters
    members = {s['id']:[m for m in meters if m['segment_id']==s['id']] for s in segments}
    # Simulator-private state: never exported as ML predictors or a precomputed risk score.
    frailty = {s['id']:rng.uniform(.3,1.6) for s in segments}
    wear = {s['id']:rng.uniform(.15,1.5) for s in segments}
    last_energy = {s['id']:deque(maxlen=7) for s in segments}
    baseline = {s['id']:sum(m['demo_base_daily_kwh'] for m in members[s['id']]) for s in segments}
    day_noise = {m['id']:0. for m in meters}
    winter = {m['id']:rng.uniform(.20,.50) for m in meters}
    summer = {m['id']:rng.uniform(.05,.25) for m in meters}
    meter_seq = {m['id']:0 for m in meters}
    vacation_until = {m['id']:-1 for m in meters}
    storms = {r['id']:0 for r in tables['regiuni']}
    regional_noise = dict.fromkeys(storms, 0.)
    events = []
    affected = []
    active = {s['id']:[] for s in segments}
    pending_repair = dict.fromkeys(active, None)
    event_affected = {}
    reading_path = out/'stats_contor.csv'
    reading_fields = ['meter_id','reading_key','seq','interval_start','interval_end','energy_kwh','received_at']
    total_readings = spikes = reduced_days = 0
    with reading_path.open('w', newline='') as file:
        writer = csv.DictWriter(file, fieldnames=reading_fields)
        writer.writeheader()
        for d in range(days):
            midnight = begin+timedelta(days=d)
            seasonal = math.cos(2*math.pi*(midnight.timetuple().tm_yday-15)/365.25)
            for rid in storms:
                if storms[rid] <= 0 and rng.random() < (.018 if seasonal > .5 else .008):
                    storms[rid] = rng.randint(2,4)
                else:
                    storms[rid] = max(0,storms[rid]-1)
                regional_noise[rid] = .65*regional_noise[rid]+rng.gauss(0,.035)
            for segment in segments:
                sid, rid = segment['id'], segment['region_id']
                repair = pending_repair[sid]
                if repair and repair['_repair_at'] <= midnight:
                    wear[sid] *= .25 if repair['repair_type']=='PERMANENT' else .7
                    pending_repair[sid] = None
                wear[sid] = min(3.5,max(0,.985*wear[sid]+.025*frailty[sid]+rng.gauss(0,.05)))
                load_history = sum(last_energy[sid])/len(last_energy[sid])/baseline[sid] if last_energy[sid] else 1.
                hazard = min(.15, .002*frailty[sid]+.008*wear[sid]**2+
                             .025*bool(storms[rid])+.008*max(0,load_history-1.25))
                # At most one uncompleted intervention per segment in this demo.
                if pending_repair[sid] is None and rng.random() < hazard:
                    occurred = midnight+timedelta(minutes=rng.randrange(1440))
                    duration = rng.randint(1,12)
                    restored = occurred+timedelta(hours=duration)
                    repaired = restored+timedelta(hours=rng.randint(4,72))
                    repair_type = rng.choices(['PERMANENT','TEMPORARY'], [.75,.25])[0]
                    event_id = uid(f'avarie-{sid}-{d}')
                    row = dict(id=event_id, segment_id=sid, occurred_at=iso(occurred),
                               reported_at=iso(occurred+timedelta(minutes=rng.randint(0,45))),
                               restored_at=iso(restored) if restored < finish else None,
                               repair_completed_at=iso(repaired) if repaired < finish else None,
                               repair_type=repair_type if repaired < finish else None,
                               severity='HIGH' if duration >= 7 else 'MEDIUM',
                               incident_type='UNPLANNED_OUTAGE', source='SYNTHETIC',
                               _start=occurred, _end=restored, _repair_at=repaired)
                    if datetime.fromisoformat(row['reported_at'].replace('Z','+00:00')) >= finish:
                        row['reported_at'] = None
                    events.append(row)
                    active[sid].append(row)
                    pending_repair[sid] = row
                    chosen = rng.sample(members[sid], rng.randint(2,7))
                    event_affected[event_id] = {m['id'] for m in chosen}
                    affected.extend(dict(incident_id=event_id,meter_id=m['id']) for m in chosen)
                active[sid] = [e for e in active[sid] if e['_end'] > midnight]
                segment_energy = 0.
                for meter in members[sid]:
                    mid, kind = meter['id'], meter['client_type']
                    day_noise[mid] = .7*day_noise[mid]+rng.gauss(0,.06)
                    seasonal_factor = (1+winter[mid]*max(seasonal,0)+summer[mid]*max(-seasonal,0)
                                       -.08*(1-abs(seasonal)))
                    weekend = midnight.weekday() >= 5
                    weekly = (1.08 if weekend else 1.) if kind=='RESIDENTIAL' else (.5 if weekend and kind=='COMMERCIAL' else .8 if weekend else 1.)
                    energy = meter['demo_base_daily_kwh']*seasonal_factor*weekly
                    energy *= max(.3,1+regional_noise[rid]+day_noise[mid]+.08*bool(storms[rid]))
                    # Slow two-year trend, not an abrupt calendar-year jump.
                    energy *= 1+.035*d/365.25
                    if rng.random() < .002:
                        vacation_until[mid] = d+rng.randint(3,10)
                    if d < vacation_until[mid]:
                        energy *= rng.uniform(.1,.3)
                        reduced_days += 1
                    weights = {'RESIDENTIAL':[.10,.25,.25,.40],
                               'COMMERCIAL':[.05,.40,.45,.10],
                               'INDUSTRIAL':[.25,.25,.25,.25]}[kind]
                    jittered = [w*rng.uniform(.9,1.1) for w in weights]
                    norm = sum(jittered)
                    spike_at = rng.randrange(4) if rng.random() < .012 else -1
                    for j in range(4):
                        t0, t1 = midnight+timedelta(hours=6*j), midnight+timedelta(hours=6*(j+1))
                        value = energy*jittered[j]/norm
                        if j == spike_at:
                            value *= rng.uniform(2,4)
                            spikes += 1
                        for event in active[sid]:
                            if mid not in event_affected[event['id']]:
                                continue
                            lo, hi = max(t0,event['_start']), min(t1,event['_end'])
                            overlap = max(0,(hi-lo).total_seconds())/21600
                            value *= 1-overlap
                        value = round(max(0,value),6)
                        meter_seq[mid] += 1
                        writer.writerow(dict(meter_id=mid,reading_key=f"{meter['external_code']}:{iso(t0)}",
                                             seq=meter_seq[mid],interval_start=iso(t0),interval_end=iso(t1),
                                             energy_kwh=value,received_at=iso(t1+timedelta(seconds=rng.randint(1,120)))))
                        total_readings += 1
                        segment_energy += value
                last_energy[sid].append(segment_energy)
    tables['stats_avarii'] = [{k:v for k,v in e.items() if not k.startswith('_')} for e in events]
    tables['avarii_contoare'] = affected
    tables['avarii_video'] = []  # Real uploads may create links later; no invented video IDs.
    fields_by_table = {name:list(rows[0]) for name,rows in tables.items() if rows}
    fields_by_table['stats_avarii'] = ['id','segment_id','occurred_at','reported_at','restored_at',
                                     'repair_completed_at','repair_type','severity','incident_type','source']
    fields_by_table['avarii_contoare'] = ['incident_id','meter_id']
    fields_by_table['avarii_video'] = ['id','incident_id','file_id']
    for name, rows in tables.items():
        with (out/f'{name}.csv').open('w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=fields_by_table[name])
            w.writeheader()
            w.writerows(rows)
    dbpath = out/'history.sqlite'
    if dbpath.exists():
        raise FileExistsError('Refusing to replace history.sqlite; choose a new --out directory')
    with sqlite3.connect(dbpath) as db:
        db.executescript((Path(__file__).parent/'schema_sqlite.sql').read_text())
        for name in ['regiuni','segmente','contoare','stats_contor','stats_avarii','avarii_contoare','avarii_video']:
            with (out/f'{name}.csv').open(newline='') as f:
                reader=csv.DictReader(f)
                columns=reader.fieldnames
                sql=f"INSERT INTO {name} ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})"
                batch=[]
                for row in reader:
                    batch.append([None if row[c]=='' else row[c] for c in columns])
                    if len(batch)==2000:
                        db.executemany(sql,batch)
                        batch=[]
                if batch:
                    db.executemany(sql,batch)
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
    manifest=dict(seed=seed,startInclusive=start,endExclusive=end,days=days,regions=3,
                  segments=18,meters=126,metersPerSegment=7,readingsPerDayPerMeter=4,
                  expectedReadings=days*126*4,readings=total_readings,outages=len(events),
                  affectedMeterLinks=len(affected),videos=0,spikes=spikes,reducedConsumptionMeterDays=reduced_days,
                  modelTrainingExecuted=False,externalDatabaseModified=False,
                  caveats=['Synthetic demonstration, not measured network behavior',
                           'UTC; partial outage reduction assumes uniform energy within each 6-hour bin',
                           'Future repair fields must be masked until their event time in any later ML',
                           'Rows with source SYNTHETIC need no fabricated video/file foreign key',
                           'demo_base_daily_kwh and profile describe the generator, not measured features'])
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2))
    return manifest


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--out',required=True)
    p.add_argument('--seed',type=int,default=42)
    p.add_argument('--start',default='2024-11-14')
    p.add_argument('--end',default='2026-11-14')
    a=p.parse_args()
    if (Path(a.out)/'history.sqlite').exists():
        p.error('history.sqlite already exists; choose a fresh output directory')
    print(json.dumps(generate(a.out,a.seed,a.start,a.end),indent=2))
