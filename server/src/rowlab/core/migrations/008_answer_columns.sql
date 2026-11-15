-- One dataset per file: runs and people add answer columns to it, instead of a run making a new dataset.
-- `datasets.parent_id`, `branch`, `made` and `root_id` stay until every tree is folded into its root
-- (`rowlab migrate`); a later migration drops them.

-- The answer columns of a dataset, one row per task and model, or per labelled task (model ''): the
-- question they answer, so a name keeps its meaning, and how many rows have an answer.
CREATE TABLE answer_columns (
    dataset_id TEXT NOT NULL REFERENCES datasets (id) ON DELETE CASCADE,
    name TEXT NOT NULL, -- the task's column, e.g. 'fallacy'
    model TEXT NOT NULL, -- e.g. 'typesafe/jev-1.14'; '' for labels people set
    task TEXT NOT NULL, -- JSON task definition
    answered INTEGER NOT NULL DEFAULT 0, -- rows with an answer (model columns; labels are counted)
    created_at TEXT NOT NULL,
    PRIMARY KEY (dataset_id, name, model)
);

-- Labels people set, a row per labelled task and row. `value` is the label as given (JSON), e.g.
-- true, "positive", ["a", "b"] or {"amount": 3}; the task's definition turns it into columns.
CREATE TABLE labels (
    dataset_id TEXT NOT NULL REFERENCES datasets (id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    row_id BIGINT NOT NULL,
    value TEXT NOT NULL,
    set_by TEXT, -- the user; empty locally
    updated_at TEXT NOT NULL,
    PRIMARY KEY (dataset_id, name, row_id)
);
