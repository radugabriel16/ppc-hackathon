CREATE SCHEMA history;

CREATE TABLE history.meters (
    id uuid PRIMARY KEY,
    external_code text NOT NULL UNIQUE,
    client_type text CHECK (client_type IN ('RESIDENTIAL','COMMERCIAL','INDUSTRIAL')),
    segment_id uuid,
    asset_id uuid NOT NULL,
    region_id uuid NOT NULL,
    region text NOT NULL
);
CREATE TABLE history.files (
    id uuid PRIMARY KEY,
    metadata jsonb NOT NULL,
    archived_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE history.file_contents (
    file_id uuid PRIMARY KEY REFERENCES history.files(id),
    content bytea NOT NULL
);
CREATE TABLE history.meter_readings (
    id uuid PRIMARY KEY,
    meter_id uuid NOT NULL REFERENCES history.meters(id),
    reading_key text NOT NULL,
    seq integer NOT NULL,
    interval_start timestamptz NOT NULL,
    interval_end timestamptz NOT NULL CHECK (interval_end > interval_start),
    energy_kwh numeric NOT NULL CHECK (energy_kwh >= 0),
    file_id uuid NOT NULL UNIQUE REFERENCES history.files(id),
    received_at timestamptz NOT NULL,
    UNIQUE (meter_id, reading_key)
);
CREATE INDEX history_readings_meter_start ON history.meter_readings(meter_id,interval_start);
CREATE INDEX history_readings_start ON history.meter_readings(interval_start);

CREATE TABLE history.synthetic_clients (id uuid PRIMARY KEY, metadata jsonb NOT NULL);
CREATE TABLE history.synthetic_cases (id uuid PRIMARY KEY, metadata jsonb NOT NULL);
CREATE TABLE history.historical_issues (id uuid PRIMARY KEY, metadata jsonb NOT NULL);
CREATE TABLE history.domain_metadata (
    kind text NOT NULL,
    id uuid NOT NULL,
    metadata jsonb NOT NULL,
    PRIMARY KEY(kind,id)
);
CREATE TABLE history.split_batches (
    id uuid PRIMARY KEY,
    kind text NOT NULL,
    source_ids uuid[] NOT NULL,
    row_count integer NOT NULL,
    digest text NOT NULL,
    backup_sha256 text NOT NULL,
    verified_at timestamptz NOT NULL DEFAULT now()
);
