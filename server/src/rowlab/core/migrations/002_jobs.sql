CREATE TABLE settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE jobs (
    id TEXT PRIMARY KEY,
    dataset_id TEXT NOT NULL REFERENCES datasets (id) ON DELETE CASCADE,
    config TEXT NOT NULL, -- JSON JobConfig
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Model responses by a hash of the request, so a paid call is never made twice.
CREATE TABLE responses (
    key TEXT PRIMARY KEY,
    response TEXT NOT NULL,
    created_at TEXT NOT NULL
);
