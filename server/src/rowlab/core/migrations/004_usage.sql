-- Who started a run (empty locally, where nobody signs in).
ALTER TABLE runs ADD COLUMN created_by TEXT;

-- What runs asked of models: a row per run, task, model and day, added to as answers come in. Kept
-- when the run's dataset is deleted, so no reference to it.
CREATE TABLE usage (
    org_id TEXT NOT NULL,
    user_id TEXT, -- who started the run
    run_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    model TEXT NOT NULL,
    paid_by TEXT NOT NULL, -- 'organisation' (its own key) or 'server' (OPENROUTER_API_KEY)
    day TEXT NOT NULL, -- e.g. '2026-11-07', UTC
    answers INTEGER NOT NULL, -- calls answered, from the cache too
    cached INTEGER NOT NULL, -- of those, answered from the cache, for free
    failed INTEGER NOT NULL,
    input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    cost REAL NOT NULL, -- USD
    PRIMARY KEY (run_id, task_id, model, paid_by, day)
);
CREATE INDEX usage_org_day ON usage (org_id, day);
