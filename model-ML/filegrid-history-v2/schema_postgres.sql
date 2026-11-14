-- Proposed standalone schema: run in a NEW database/schema after integration review.
-- Does not modify an existing FileGrid installation; no DROP or model tables.
BEGIN;
CREATE TABLE regiuni(id UUID PRIMARY KEY, code TEXT UNIQUE NOT NULL);
CREATE TABLE segmente(id UUID PRIMARY KEY, region_id UUID NOT NULL REFERENCES regiuni(id), code TEXT UNIQUE NOT NULL);
CREATE TABLE contoare(id UUID PRIMARY KEY, external_code TEXT UNIQUE NOT NULL,
 segment_id UUID NOT NULL REFERENCES segmente(id), client_type TEXT NOT NULL,
 consumption_profile TEXT NOT NULL, demo_base_daily_kwh NUMERIC(18,6) NOT NULL CHECK(demo_base_daily_kwh>0));
CREATE TABLE stats_contor(meter_id UUID NOT NULL REFERENCES contoare(id), reading_key TEXT PRIMARY KEY,
 seq BIGINT NOT NULL CHECK(seq>0), interval_start TIMESTAMPTZ NOT NULL, interval_end TIMESTAMPTZ NOT NULL,
 energy_kwh NUMERIC(18,6) NOT NULL CHECK(energy_kwh>=0), received_at TIMESTAMPTZ NOT NULL,
 UNIQUE(meter_id,seq), UNIQUE(meter_id,interval_start), CHECK(interval_end>interval_start));
CREATE TABLE stats_avarii(id UUID PRIMARY KEY, segment_id UUID NOT NULL REFERENCES segmente(id),
 occurred_at TIMESTAMPTZ NOT NULL, reported_at TIMESTAMPTZ, restored_at TIMESTAMPTZ, repair_completed_at TIMESTAMPTZ,
 repair_type TEXT CHECK(repair_type IN ('TEMPORARY','PERMANENT')), severity TEXT NOT NULL,
 incident_type TEXT NOT NULL, source TEXT NOT NULL CHECK(source IN ('SYNTHETIC','UPLOAD')),
 CHECK(reported_at IS NULL OR reported_at>=occurred_at),
 CHECK(restored_at IS NULL OR restored_at>occurred_at),
 CHECK(repair_completed_at IS NULL OR (restored_at IS NOT NULL AND repair_completed_at>=restored_at)),
 CHECK((repair_completed_at IS NULL)=(repair_type IS NULL)));
CREATE TABLE avarii_contoare(incident_id UUID REFERENCES stats_avarii(id),meter_id UUID REFERENCES contoare(id),
 PRIMARY KEY(incident_id,meter_id));
-- Connect file_id to the real file catalog during integration; do not fabricate files.
CREATE TABLE avarii_video(id UUID PRIMARY KEY,incident_id UUID NOT NULL REFERENCES stats_avarii(id),file_id UUID UNIQUE NOT NULL);
CREATE INDEX ix_segment_region ON segmente(region_id);
CREATE INDEX ix_meter_segment ON contoare(segment_id);
CREATE INDEX ix_reading_meter_time ON stats_contor(meter_id,interval_start);
CREATE INDEX ix_outage_segment_time ON stats_avarii(segment_id,occurred_at);
CREATE INDEX ix_affected_meter ON avarii_contoare(meter_id);
COMMIT;
