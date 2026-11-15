-- The models a run asks, by id, with their kinds and prices as when it started (JSON), so its runner
-- needs no catalog: a model may since have left rowlab's list or OpenRouter's catalog. Empty for runs
-- from before, which look their models up.
ALTER TABLE runs ADD COLUMN models TEXT NOT NULL DEFAULT '{}';
