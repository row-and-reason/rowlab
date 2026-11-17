-- A run started again from an ended one, to ask what that one didn't get: the two are one piece of
-- work, shown as one. And how many of a run's answers were replies kept from earlier runs, free.
-- Answers in the chunk being asked are counted apart until it is written, so a chunk asked again
-- (its runner shut down or died) replaces them instead of adding to them.
ALTER TABLE runs ADD COLUMN resumes TEXT;
ALTER TABLE runs ADD COLUMN reused INTEGER NOT NULL DEFAULT 0;
ALTER TABLE runs ADD COLUMN chunk_done INTEGER NOT NULL DEFAULT 0;
ALTER TABLE runs ADD COLUMN chunk_reused INTEGER NOT NULL DEFAULT 0;
