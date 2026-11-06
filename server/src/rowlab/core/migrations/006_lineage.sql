-- Every run makes a new dataset as it goes, and the run belongs to that dataset. Runs and the
-- datasets they produced before are dropped (prototype); their files are left behind.
DELETE FROM datasets WHERE run_id IS NOT NULL;
DROP TABLE runs;
CREATE TABLE runs (
    id TEXT PRIMARY KEY,
    dataset_id TEXT NOT NULL REFERENCES datasets (id) ON DELETE CASCADE, -- the dataset it makes
    number INTEGER NOT NULL, -- 1, 2, … per parent dataset
    status TEXT NOT NULL,
    config TEXT NOT NULL, -- JSON JobConfig, frozen when the run started
    columns TEXT NOT NULL, -- JSON list of answer columns
    costs TEXT NOT NULL, -- JSON list of TaskModelCost
    row_count INTEGER NOT NULL,
    next_chunk INTEGER NOT NULL DEFAULT 0, -- first chunk not yet written
    done INTEGER NOT NULL DEFAULT 0, -- model calls answered so far
    total INTEGER NOT NULL, -- model calls the run makes
    cost REAL NOT NULL DEFAULT 0,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT
);
ALTER TABLE datasets DROP COLUMN run_id;

-- Every dataset is stored as Parquet, so names no longer carry the original file's extension.
ALTER TABLE datasets DROP COLUMN format;
UPDATE datasets SET name = substr(name, 1, length(name) - 3) WHERE lower(name) LIKE '%.gz';
UPDATE datasets SET name = substr(name, 1, length(name) - 4) WHERE lower(name) LIKE '%.csv';
UPDATE datasets SET name = substr(name, 1, length(name) - 4) WHERE lower(name) LIKE '%.tsv';
UPDATE datasets SET name = substr(name, 1, length(name) - 5) WHERE lower(name) LIKE '%.json';
UPDATE datasets SET name = substr(name, 1, length(name) - 6) WHERE lower(name) LIKE '%.jsonl';
UPDATE datasets SET name = substr(name, 1, length(name) - 7) WHERE lower(name) LIKE '%.ndjson';
UPDATE datasets SET name = substr(name, 1, length(name) - 8) WHERE lower(name) LIKE '%.parquet';
