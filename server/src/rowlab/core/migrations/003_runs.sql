CREATE TABLE runs (
    id TEXT PRIMARY KEY,
    dataset_id TEXT NOT NULL REFERENCES datasets (id) ON DELETE CASCADE,
    number INTEGER NOT NULL, -- 1, 2, … per dataset
    config TEXT NOT NULL, -- JSON JobConfig, frozen when the run started
    columns TEXT NOT NULL, -- JSON list of answer columns
    costs TEXT NOT NULL, -- JSON list of TaskModelCost
    row_count INTEGER NOT NULL,
    cost REAL NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE run_rows (
    run_id TEXT NOT NULL REFERENCES runs (id) ON DELETE CASCADE,
    row_id INTEGER NOT NULL,
    vals TEXT NOT NULL, -- JSON: answer columns and their `_proba` columns
    errors TEXT NOT NULL, -- JSON: why an answer column is missing, by column
    PRIMARY KEY (run_id, row_id)
);
