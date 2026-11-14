-- storage-db: content-only database, no business/catalog data.
-- Applied once on first container start via the official postgres
-- docker-entrypoint-initdb.d mechanism.
CREATE TABLE IF NOT EXISTS file_contents (
    file_id UUID PRIMARY KEY,
    content BYTEA NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Also upgrade volumes initialized before orphan collection was introduced.
ALTER TABLE file_contents ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT now();
CREATE INDEX IF NOT EXISTS ix_file_contents_created_at ON file_contents (created_at);
