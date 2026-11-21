-- Settled datasets: those left alone, listed apart. `settled_at` is when an admin settled one, until
-- something happens on it; `unsettled_at` when one was brought back, which counts as activity, so
-- it doesn't settle again straight away; `auto_settle` the dataset's own choice (1 on, 0 off) over
-- the organisation's (`settings` key `auto_settle`), or NULL to follow it.
ALTER TABLE datasets ADD COLUMN settled_at TEXT;
ALTER TABLE datasets ADD COLUMN unsettled_at TEXT;
ALTER TABLE datasets ADD COLUMN auto_settle INTEGER;
