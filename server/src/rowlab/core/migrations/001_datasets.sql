CREATE TABLE datasets (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    source TEXT NOT NULL,
    format TEXT NOT NULL,
    row_count INTEGER NOT NULL,
    size_bytes INTEGER NOT NULL,
    columns TEXT NOT NULL, -- JSON list of {"name", "type"}
    created_at TEXT NOT NULL
);
