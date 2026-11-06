-- Runs execute in the background: `running` until they are `done` or `failed`.
ALTER TABLE runs ADD COLUMN status TEXT NOT NULL DEFAULT 'done';
ALTER TABLE runs ADD COLUMN done INTEGER NOT NULL DEFAULT 0; -- model calls answered so far
ALTER TABLE runs ADD COLUMN total INTEGER NOT NULL DEFAULT 0; -- model calls the run makes
ALTER TABLE runs ADD COLUMN error TEXT;
UPDATE runs SET done = row_count, total = row_count;
