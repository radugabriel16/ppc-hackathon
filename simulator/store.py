"""One SQLite writer; payload bytes, sequence and cursor commit atomically."""
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path


def iso(value):
    return value.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')


class Store:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
            PRAGMA journal_mode=WAL;
            PRAGMA synchronous=FULL;
            CREATE TABLE IF NOT EXISTS meters(code TEXT PRIMARY KEY, seq INTEGER NOT NULL,
                next_start TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS generated(reading_key TEXT PRIMARY KEY, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS outbox(id INTEGER PRIMARY KEY, payload TEXT NOT NULL,
                run_id TEXT, attempts INTEGER NOT NULL DEFAULT 0, due REAL NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS outbox_due ON outbox(due, id);
        ''')

    def get(self, key, default=None):
        row = self.db.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set(self, key, value):
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO meta VALUES (?,?)', (key, json.dumps(value)))

    def run(self, run):
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO runs VALUES (?,?)', (run['id'], json.dumps(run)))

    def runs(self):
        return [json.loads(r[0]) for r in self.db.execute('SELECT data FROM runs ORDER BY rowid DESC')]

    def count(self):
        return self.db.execute('SELECT count(*) FROM outbox').fetchone()[0]

    def enqueue(self, meter, energy, run_id, start=None, gap=False, job=None):
        code = meter['externalCode']
        with self.db:
            row = self.db.execute('SELECT seq,next_start FROM meters WHERE code=?', (code,)).fetchone()
            seq = row['seq'] + 1 if row else 1
            now = datetime.now(timezone.utc)
            initial = now.replace(minute=now.minute // 15 * 15, second=0, microsecond=0)
            begin = start or (datetime.fromisoformat(row['next_start']) if row else initial)
            key = f'{code}:{iso(begin)}'
            known = self.db.execute('SELECT payload FROM generated WHERE reading_key=?', (key,)).fetchone()
            if known:
                if job is not None:
                    self.db.execute('INSERT OR REPLACE INTO meta VALUES (?,?)', ('backfill', json.dumps(job)))
                return known[0]
            if seq > 2147483647:
                raise ValueError('Meter sequence exhausted')
            end = begin + timedelta(minutes=15)
            # Backfill cannot rewind the live cursor.
            next_start = max(end, datetime.fromisoformat(row['next_start'])) if row else end
            self.db.execute('INSERT OR REPLACE INTO meters VALUES (?,?,?)', (code, seq, iso(next_start)))
            payload = json.dumps(dict(meterExternalCode=code, readingKey=f'{code}:{iso(begin)}',
                seq=seq, intervalStart=iso(begin), intervalEnd=iso(end), energyKwh=energy),
                separators=(',', ':'))
            self.db.execute('INSERT INTO generated VALUES (?,?)', (key, payload))
            record = self.db.execute('SELECT data FROM runs WHERE id=?', (run_id,)).fetchone()
            if record:
                run = json.loads(record[0])
                counter = 'intentionalGaps' if gap else 'generated'
                run['counters'][counter] = run['counters'].get(counter, 0) + 1
                self.db.execute('UPDATE runs SET data=? WHERE id=?', (json.dumps(run), run_id))
            if not gap:
                self.db.execute('INSERT INTO outbox(payload,run_id) VALUES (?,?)', (payload, run_id))
            if job is not None:
                self.db.execute('INSERT OR REPLACE INTO meta VALUES (?,?)', ('backfill', json.dumps(job)))
        return payload

    def next(self, now):
        return self.db.execute('SELECT * FROM outbox WHERE due<=? ORDER BY id LIMIT 1', (now,)).fetchone()

    def retry(self, row, due):
        with self.db:
            self.db.execute('UPDATE outbox SET attempts=attempts+1,due=? WHERE id=?', (due, row['id']))

    def ack(self, row, result):
        with self.db:
            self.db.execute('DELETE FROM outbox WHERE id=?', (row['id'],))
            record = self.db.execute('SELECT data FROM runs WHERE id=?', (row['run_id'],)).fetchone()
            if record:
                run = json.loads(record[0])
                counters = run['counters']
                counters[result] = counters.get(result, 0) + 1
                self.db.execute('UPDATE runs SET data=? WHERE id=?', (json.dumps(run), row['run_id']))
