-- storage-db: content-only database, no business/catalog data.
-- Applied once on first container start via the official postgres
-- docker-entrypoint-initdb.d mechanism.
CREATE TABLE IF NOT EXISTS file_contents (
    file_id UUID PRIMARY KEY,
    content BYTEA NOT NULL
);
