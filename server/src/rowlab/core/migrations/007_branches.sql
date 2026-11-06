-- Datasets made by runs are named after the file their tree started from, plus their branch, numbered
-- like an outline: `titanic` for the file itself, `titanic__1`, `titanic__2`, … for datasets made from
-- it, `titanic__1.1` for the first made from `titanic__1`. Runs lose their own numbers.
ALTER TABLE datasets ADD COLUMN branch TEXT; -- e.g. '1.2'; NULL for a dataset added from a file
ALTER TABLE datasets ADD COLUMN made INTEGER NOT NULL DEFAULT 0; -- datasets made from it so far
WITH RECURSIVE numbered (id, parent_id, n) AS (
    SELECT id, parent_id, row_number() OVER (PARTITION BY parent_id ORDER BY created_at)
    FROM datasets WHERE parent_id IN (SELECT id FROM datasets)
),
tree (id, base, branch) AS (
    SELECT id, name, NULL FROM datasets
    WHERE parent_id IS NULL OR parent_id NOT IN (SELECT id FROM datasets)
    UNION ALL
    SELECT n.id, t.base, coalesce(t.branch || '.', '') || n.n FROM numbered n JOIN tree t ON n.parent_id = t.id
)
UPDATE datasets SET
    branch = (SELECT branch FROM tree WHERE tree.id = datasets.id),
    name = (SELECT base || coalesce('__' || branch, '') FROM tree WHERE tree.id = datasets.id);
UPDATE datasets SET made = (SELECT count(*) FROM datasets c WHERE c.parent_id = datasets.id);
UPDATE datasets SET source = 'Made from ' || (SELECT p.name FROM datasets p WHERE p.id = datasets.parent_id)
WHERE parent_id IN (SELECT id FROM datasets);
ALTER TABLE runs DROP COLUMN number;
