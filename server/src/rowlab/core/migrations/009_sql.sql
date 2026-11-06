-- Rows are picked with SQL, and drafts of runs live in the browser. Jobs go; runs keep their tasks,
-- and a query for all rows in place of their old scope (prototype: the scope itself is dropped).
DROP TABLE jobs;
UPDATE runs SET config = json_set(json_remove(config, '$.scope'), '$.sql', 'SELECT * FROM data');
