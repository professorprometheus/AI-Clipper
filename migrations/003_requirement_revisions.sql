CREATE TABLE IF NOT EXISTS requirement_revisions (
  id TEXT PRIMARY KEY,
  requirement_id TEXT NOT NULL REFERENCES campaign_requirements(id),
  campaign_id TEXT NOT NULL REFERENCES campaigns(id),
  previous_json TEXT NOT NULL,
  replacement_json TEXT NOT NULL,
  reason TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_requirement_revisions_requirement
  ON requirement_revisions(requirement_id, created_at);

