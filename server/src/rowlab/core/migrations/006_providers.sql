-- Model providers an organisation saves: OpenRouter or LiteLLM, each a base URL and its own key. The
-- active one is the `active_provider` setting. The key is never returned by the API.
CREATE TABLE providers (
    id TEXT PRIMARY KEY,
    org_id TEXT NOT NULL,
    name TEXT NOT NULL,
    type TEXT NOT NULL, -- 'openrouter' or 'litellm'
    base_url TEXT NOT NULL, -- e.g. 'https://openrouter.ai/api', without '/v1'
    model_prefix TEXT NOT NULL, -- before rowlab's model ids, e.g. 'openrouter/' for a gateway
    api_key TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX providers_org ON providers (org_id);

-- The provider a run's calls go to, kept from when it started. Empty when the server's key paid
-- (OPENROUTER_API_KEY), and for runs from before providers, which use the active one.
ALTER TABLE runs ADD COLUMN provider_id TEXT;

-- A saved OpenRouter key becomes the organisation's active provider.
INSERT INTO providers (id, org_id, name, type, base_url, model_prefix, api_key, created_at)
SELECT 'openrouter-' || org_id, org_id, 'OpenRouter', 'openrouter', 'https://openrouter.ai/api', '',
    value, '2026-11-15T00:00:00+00:00'
FROM settings WHERE key = 'openrouter_api_key';
UPDATE settings SET key = 'active_provider', value = 'openrouter-' || org_id
WHERE key = 'openrouter_api_key';
