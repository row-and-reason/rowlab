-- Organisations, the people in them and how they sign in. Everything else belongs to an organisation
-- (`org_id`): locally that is always 'local', which has no row here, since there is no sign-in.

CREATE TABLE orgs (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL
);

-- People, as WorkOS knows them.
CREATE TABLE users (
    id TEXT PRIMARY KEY,
    workos_id TEXT NOT NULL UNIQUE,
    email TEXT NOT NULL UNIQUE, -- lowercase
    name TEXT NOT NULL,
    created_at TEXT NOT NULL
);

-- Who is in which organisation, as admin, member or verifier.
CREATE TABLE members (
    org_id TEXT NOT NULL REFERENCES orgs (id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (org_id, user_id)
);

-- People asked to join an organisation; they join when they first sign in.
CREATE TABLE invites (
    id TEXT PRIMARY KEY,
    org_id TEXT NOT NULL REFERENCES orgs (id) ON DELETE CASCADE,
    email TEXT NOT NULL, -- lowercase
    role TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (org_id, email)
);

-- Signed-in browsers. The cookie holds a token; only its hash is kept.
CREATE TABLE sessions (
    id TEXT PRIMARY KEY, -- sha256 of the token
    user_id TEXT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    org_id TEXT NOT NULL REFERENCES orgs (id) ON DELETE CASCADE,
    workos_session_id TEXT NOT NULL, -- to sign out of WorkOS too
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

-- API keys (`rl_…`), each acting as the person who made it. Only their hash is kept.
CREATE TABLE api_keys (
    id TEXT PRIMARY KEY,
    hash TEXT NOT NULL UNIQUE, -- sha256 of the key
    user_id TEXT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    org_id TEXT NOT NULL REFERENCES orgs (id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_used_at TEXT
);

ALTER TABLE datasets ADD COLUMN org_id TEXT NOT NULL DEFAULT 'local';
CREATE INDEX datasets_org_id ON datasets (org_id);

ALTER TABLE connections ADD COLUMN org_id TEXT NOT NULL DEFAULT 'local';

-- Settings are per organisation now.
CREATE TABLE org_settings (
    org_id TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    PRIMARY KEY (org_id, key)
);
INSERT INTO org_settings (org_id, key, value) SELECT 'local', key, value FROM settings;
DROP TABLE settings;
ALTER TABLE org_settings RENAME TO settings;
