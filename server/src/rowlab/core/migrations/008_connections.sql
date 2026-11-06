-- Named connections to S3-compatible storage. The secret key is stored as is (see ROADMAP risks) and
-- never returned by the API.
CREATE TABLE connections (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    endpoint TEXT NOT NULL, -- '' for AWS; e.g. 'https://<account>.r2.cloudflarestorage.com'
    region TEXT NOT NULL,
    access_key_id TEXT NOT NULL,
    secret_access_key TEXT NOT NULL,
    created_at TEXT NOT NULL
);
