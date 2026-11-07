-- Runners take turns: a run does one chunk, then waits in the queue again (see `runs.process_next`).

-- When the run last joined the queue; runs waiting longest go first.
ALTER TABLE runs ADD COLUMN queued_at TEXT;
UPDATE runs SET queued_at = coalesce(updated_at, created_at);

-- The next written chunk whose failed answers a resumed run asks again; NULL once they all have been.
ALTER TABLE runs ADD COLUMN retry_chunk INTEGER;
