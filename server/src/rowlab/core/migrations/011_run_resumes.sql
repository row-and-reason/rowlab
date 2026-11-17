-- A run started again from an ended one, to ask what that one didn't get: the two are one piece of
-- work, shown as one. And how many of a run's answers were replies kept from earlier runs, free.
ALTER TABLE runs ADD COLUMN resumes TEXT;
ALTER TABLE runs ADD COLUMN reused INTEGER NOT NULL DEFAULT 0;
