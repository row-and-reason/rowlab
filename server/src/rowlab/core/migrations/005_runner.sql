-- Runs are processed in chunks by one runner thread, and their answers live in Parquet files
-- (`runs/{id}/part-*.parquet`), not in the database. Runs from before are dropped (prototype).
DELETE FROM runs;
DROP TABLE run_rows;
ALTER TABLE runs ADD COLUMN next_chunk INTEGER NOT NULL DEFAULT 0; -- first chunk not yet written
ALTER TABLE runs ADD COLUMN updated_at TEXT;
ALTER TABLE runs ADD COLUMN output_dataset_id TEXT;

-- Datasets produced by a run record where they came from.
ALTER TABLE datasets ADD COLUMN parent_id TEXT;
ALTER TABLE datasets ADD COLUMN run_id TEXT;
