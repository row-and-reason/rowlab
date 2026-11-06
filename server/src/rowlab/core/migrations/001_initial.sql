-- rowlab's database: datasets, the runs that make them, saved settings and connections, and the
-- response cache. Later changes go in new numbered files, safe to apply to existing databases.

-- A dataset: a file added, or what a run made from another dataset (`parent_id`). Its rows live in
-- `datasets/{id}/` as Parquet. A made dataset is named after its branch, e.g. `titanic__1.2`.
CREATE TABLE datasets (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    source TEXT NOT NULL,
    row_count INTEGER NOT NULL,
    size_bytes INTEGER NOT NULL,
    columns TEXT NOT NULL, -- JSON list of {"name", "type"}
    created_at TEXT NOT NULL,
    parent_id TEXT, -- the dataset a run made it from
    branch TEXT, -- e.g. '1.2'; NULL for a dataset added from a file
    made INTEGER NOT NULL DEFAULT 0 -- datasets made from it so far, numbering the next
);

-- A run: tasks asked about the rows a query picks, making a new dataset (`dataset_id`). Its answers
-- live with that dataset, one Parquet part per chunk of rows.
CREATE TABLE runs (
    id TEXT PRIMARY KEY,
    dataset_id TEXT NOT NULL REFERENCES datasets (id) ON DELETE CASCADE, -- the dataset it makes
    status TEXT NOT NULL, -- queued, running, stopping, stopped, done, failed
    config TEXT NOT NULL, -- JSON {sql, tasks}, frozen when the run started
    columns TEXT NOT NULL, -- JSON list of answer columns
    costs TEXT NOT NULL, -- JSON list of cost and failed answers per task and model
    row_count INTEGER NOT NULL, -- rows it asks about
    next_chunk INTEGER NOT NULL DEFAULT 0, -- first chunk not yet written
    done INTEGER NOT NULL DEFAULT 0, -- model calls answered so far
    total INTEGER NOT NULL, -- model calls the run makes
    cost REAL NOT NULL DEFAULT 0,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT
);

-- Settings saved from the UI, e.g. the OpenRouter key.
CREATE TABLE settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Named connections to S3-compatible storage. The secret key is never returned by the API.
CREATE TABLE connections (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    endpoint TEXT NOT NULL, -- '' for AWS; e.g. 'https://<account>.r2.cloudflarestorage.com'
    region TEXT NOT NULL,
    access_key_id TEXT NOT NULL,
    secret_access_key TEXT NOT NULL,
    created_at TEXT NOT NULL
);

-- Model replies by a hash of the request, so the same question is never paid for twice.
CREATE TABLE responses (
    key TEXT PRIMARY KEY,
    response TEXT NOT NULL,
    created_at TEXT NOT NULL
);
