CREATE TABLE IF NOT EXISTS research_imports (
  id TEXT PRIMARY KEY,
  campaign_id TEXT NOT NULL REFERENCES campaigns(id),
  platform TEXT NOT NULL,
  url TEXT NOT NULL,
  creator TEXT NOT NULL,
  published_hours_ago REAL NOT NULL,
  metrics_json TEXT NOT NULL,
  baseline_json TEXT NOT NULL,
  transcript TEXT NOT NULL,
  labels_json TEXT NOT NULL,
  raw_json TEXT NOT NULL,
  provenance TEXT NOT NULL,
  imported_at TEXT NOT NULL,
  UNIQUE(campaign_id, url)
);

CREATE TABLE IF NOT EXISTS creator_profiles (
  id TEXT PRIMARY KEY,
  campaign_id TEXT NOT NULL REFERENCES campaigns(id),
  platform TEXT NOT NULL,
  creator TEXT NOT NULL,
  metrics_json TEXT NOT NULL,
  evidence_ids_json TEXT NOT NULL,
  successful_clipper INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(campaign_id, platform, creator)
);

