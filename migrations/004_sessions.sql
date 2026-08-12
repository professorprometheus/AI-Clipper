CREATE TABLE IF NOT EXISTS app_sessions (
  id TEXT PRIMARY KEY,
  session_hash TEXT NOT NULL UNIQUE,
  csrf_hash TEXT NOT NULL,
  email TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  revoked_at TEXT,
  created_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_app_sessions_expiry
  ON app_sessions(expires_at, revoked_at);

