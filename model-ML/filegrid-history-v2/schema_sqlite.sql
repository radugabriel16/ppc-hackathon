PRAGMA foreign_keys = ON;
CREATE TABLE regiuni(id TEXT PRIMARY KEY, code TEXT UNIQUE NOT NULL);
CREATE TABLE segmente(id TEXT PRIMARY KEY, region_id TEXT NOT NULL REFERENCES regiuni(id), code TEXT UNIQUE NOT NULL);
CREATE TABLE contoare(id TEXT PRIMARY KEY, external_code TEXT UNIQUE NOT NULL,
 segment_id TEXT NOT NULL REFERENCES segmente(id), client_type TEXT NOT NULL,
 consumption_profile TEXT NOT NULL, demo_base_daily_kwh NUMERIC NOT NULL CHECK(demo_base_daily_kwh>0));
CREATE TABLE stats_contor(meter_id TEXT NOT NULL REFERENCES contoare(id), reading_key TEXT PRIMARY KEY,
 seq INTEGER NOT NULL CHECK(seq>0), interval_start TEXT NOT NULL, interval_end TEXT NOT NULL,
 energy_kwh NUMERIC NOT NULL CHECK(energy_kwh>=0), received_at TEXT NOT NULL,
 UNIQUE(meter_id,seq), UNIQUE(meter_id,interval_start), CHECK(interval_end>interval_start));
CREATE TABLE stats_avarii(id TEXT PRIMARY KEY, segment_id TEXT NOT NULL REFERENCES segmente(id),
 occurred_at TEXT NOT NULL, reported_at TEXT, restored_at TEXT, repair_completed_at TEXT,
 repair_type TEXT CHECK(repair_type IN ('TEMPORARY','PERMANENT')), severity TEXT NOT NULL,
 incident_type TEXT NOT NULL, source TEXT NOT NULL CHECK(source IN ('SYNTHETIC','UPLOAD')),
 CHECK(reported_at IS NULL OR reported_at>=occurred_at),
 CHECK(restored_at IS NULL OR restored_at>occurred_at),
 CHECK(repair_completed_at IS NULL OR (restored_at IS NOT NULL AND repair_completed_at>=restored_at)),
 CHECK((repair_completed_at IS NULL)=(repair_type IS NULL)));
CREATE TABLE avarii_contoare(incident_id TEXT REFERENCES stats_avarii(id),meter_id TEXT REFERENCES contoare(id),
 PRIMARY KEY(incident_id,meter_id));
-- file_id points to the application's future file catalog; integrate its FK there.
CREATE TABLE avarii_video(id TEXT PRIMARY KEY,incident_id TEXT NOT NULL REFERENCES stats_avarii(id),file_id TEXT UNIQUE NOT NULL);
CREATE INDEX ix_segment_region ON segmente(region_id);
CREATE INDEX ix_meter_segment ON contoare(segment_id);
CREATE INDEX ix_reading_meter_time ON stats_contor(meter_id,interval_start);
CREATE INDEX ix_outage_segment_time ON stats_avarii(segment_id,occurred_at);
CREATE INDEX ix_affected_meter ON avarii_contoare(meter_id);
