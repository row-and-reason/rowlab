-- The columns of the layout where a run made a new dataset in a tree. Every tree was folded into its
-- root by a one-off `rowlab migrate`, which `rowlab serve` and `rowlab runner` required before they
-- would start.
DROP INDEX datasets_root;
ALTER TABLE datasets DROP COLUMN root_id;
ALTER TABLE datasets DROP COLUMN parent_id;
ALTER TABLE datasets DROP COLUMN branch;
ALTER TABLE datasets DROP COLUMN made;
