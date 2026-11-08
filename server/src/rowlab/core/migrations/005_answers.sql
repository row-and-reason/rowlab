-- Model replies live with the datasets runs make (`answers/*.parquet`), and go when they are deleted.
-- The database keeps only the replies of chunks still under way (see `answers.py`).
DROP TABLE responses;

-- Replies paid for in a chunk not yet written, so a stop or crash doesn't pay for them again.
-- Cleared once the chunk is written.
CREATE TABLE answer_journal (
    run_id TEXT NOT NULL REFERENCES runs (id) ON DELETE CASCADE,
    key TEXT NOT NULL, -- the request's hash
    row_id BIGINT NOT NULL,
    data TEXT NOT NULL, -- JSON: the decision answers, or the reply's text
    PRIMARY KEY (run_id, key)
);

-- The dataset added from a file that a dataset was made from, through any number of runs. Datasets
-- of one tree share `__row_id`s, and runs reuse the answers in their tree.
ALTER TABLE datasets ADD COLUMN root_id TEXT;
WITH RECURSIVE up (id, ancestor, parent) AS (
    SELECT id, id, parent_id FROM datasets
    UNION ALL
    SELECT up.id, up.parent, d.parent_id
    FROM up LEFT JOIN datasets d ON d.id = up.parent
    WHERE up.parent IS NOT NULL
)
UPDATE datasets SET root_id = (
    SELECT ancestor FROM up WHERE up.id = datasets.id AND up.parent IS NULL
);
CREATE INDEX datasets_root ON datasets (root_id);
