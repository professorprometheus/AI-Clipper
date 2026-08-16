ALTER TABLE campaigns ADD COLUMN raw_brief TEXT;
ALTER TABLE campaigns ADD COLUMN enrichment_config_json TEXT NOT NULL DEFAULT '{}';
ALTER TABLE candidate_moments ADD COLUMN enrichment_suitability_json TEXT NOT NULL DEFAULT '{}';

CREATE TABLE IF NOT EXISTS assets (
  id TEXT PRIMARY KEY,
  campaign_id TEXT REFERENCES campaigns(id),
  asset_type TEXT NOT NULL,
  file_uri TEXT NOT NULL,
  title TEXT NOT NULL,
  tags_json TEXT NOT NULL,
  semantic_description TEXT NOT NULL,
  duration_ms INTEGER,
  licence TEXT NOT NULL,
  permitted_commercial_use INTEGER NOT NULL,
  attribution_requirement TEXT,
  source_url TEXT,
  campaign_restrictions_json TEXT NOT NULL,
  embedding_json TEXT NOT NULL,
  metadata_json TEXT NOT NULL,
  rights_attestation TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_assets_campaign_type
  ON assets(campaign_id, asset_type, created_at);

CREATE TABLE IF NOT EXISTS enrichment_plans (
  id TEXT PRIMARY KEY,
  campaign_id TEXT NOT NULL REFERENCES campaigns(id),
  candidate_id TEXT NOT NULL REFERENCES candidate_moments(id),
  version INTEGER NOT NULL,
  plan_json TEXT NOT NULL,
  strategy_features_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(candidate_id, version)
);
CREATE INDEX IF NOT EXISTS idx_enrichment_plans_campaign
  ON enrichment_plans(campaign_id, created_at);
