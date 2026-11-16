-- Provider types are named for the API they speak: LiteLLM's is OpenAI's, which vLLM serves too.
UPDATE providers SET type = 'openai' WHERE type = 'litellm';

-- An organisation's own models, beside rowlab's catalog: each asked through one of its providers, by
-- the name that provider gives it. A deleted model keeps its row (`deleted_at`), so its id, which
-- answer columns and kept replies go by, is never given to other weights.
CREATE TABLE models (
    org_id TEXT NOT NULL,
    id TEXT NOT NULL, -- rowlab's id, e.g. 'fallacy-ft-step-2000'; no '/', unlike catalog ids
    kind TEXT NOT NULL, -- 'decision' or 'llm'
    provider_id TEXT NOT NULL,
    upstream TEXT NOT NULL, -- what the provider calls it, e.g. 'step-2000'
    note TEXT NOT NULL, -- what answers, e.g. a revision or training run
    prompt_price DOUBLE PRECISION, -- USD per token; NULL when unknown, e.g. a GPU paid by the hour
    completion_price DOUBLE PRECISION,
    created_by TEXT,
    created_at TEXT NOT NULL,
    deleted_at TEXT,
    PRIMARY KEY (org_id, id)
);
