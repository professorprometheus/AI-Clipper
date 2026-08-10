PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_migrations (
  version TEXT PRIMARY KEY, applied_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS campaigns (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, owner_email TEXT NOT NULL,
  platform TEXT NOT NULL, campaign_url TEXT, payout_model TEXT, payout_value REAL,
  currency TEXT NOT NULL DEFAULT 'GBP', deadline TEXT, status TEXT NOT NULL,
  research_seeds_json TEXT NOT NULL, target_platforms_json TEXT NOT NULL,
  watermark_json TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS campaign_requirements (
  id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL REFERENCES campaigns(id),
  key TEXT NOT NULL, requirement_type TEXT NOT NULL, operator TEXT NOT NULL,
  value_json TEXT NOT NULL, severity TEXT NOT NULL, source_text TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS approved_sources (
  id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL REFERENCES campaigns(id),
  source_type TEXT NOT NULL, url TEXT NOT NULL, canonical_url TEXT NOT NULL,
  title TEXT, status TEXT NOT NULL, metadata_json TEXT NOT NULL, created_at TEXT NOT NULL,
  UNIQUE(campaign_id, canonical_url)
);
CREATE TABLE IF NOT EXISTS successful_examples (
  id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL REFERENCES campaigns(id),
  url TEXT NOT NULL, canonical_url TEXT NOT NULL, platform TEXT, creator TEXT,
  metrics_json TEXT NOT NULL, transcript TEXT, analysis_json TEXT, created_at TEXT NOT NULL,
  UNIQUE(campaign_id, canonical_url)
);
CREATE TABLE IF NOT EXISTS research_targets (
  id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL REFERENCES campaigns(id),
  target_type TEXT NOT NULL, value TEXT NOT NULL, UNIQUE(campaign_id, target_type, value)
);
CREATE TABLE IF NOT EXISTS pipeline_jobs (
  id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL REFERENCES campaigns(id), job_type TEXT NOT NULL,
  status TEXT NOT NULL, current_stage TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
  worker_token TEXT, lease_expires_at TEXT, heartbeat_at TEXT, checkpoint_json TEXT NOT NULL,
  error_json TEXT, idempotency_key TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jobs_acquire ON pipeline_jobs(status, lease_expires_at, created_at);
CREATE TABLE IF NOT EXISTS stage_runs (
  id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES pipeline_jobs(id), stage TEXT NOT NULL,
  status TEXT NOT NULL, attempt INTEGER NOT NULL, output_json TEXT NOT NULL,
  started_at TEXT NOT NULL, completed_at TEXT, UNIQUE(job_id, stage, status)
);
CREATE TABLE IF NOT EXISTS source_items (
  id TEXT PRIMARY KEY, approved_source_id TEXT NOT NULL REFERENCES approved_sources(id),
  campaign_id TEXT NOT NULL REFERENCES campaigns(id), external_id TEXT NOT NULL,
  source_url TEXT NOT NULL, title TEXT NOT NULL, duration_ms INTEGER NOT NULL,
  channel TEXT, published_at TEXT, metadata_json TEXT NOT NULL,
  UNIQUE(approved_source_id, external_id)
);
CREATE TABLE IF NOT EXISTS transcript_segments (
  id TEXT PRIMARY KEY, source_item_id TEXT NOT NULL REFERENCES source_items(id),
  start_ms INTEGER NOT NULL, end_ms INTEGER NOT NULL, text TEXT NOT NULL,
  embedding_json TEXT NOT NULL, UNIQUE(source_item_id, start_ms, end_ms)
);
CREATE TABLE IF NOT EXISTS style_profiles (
  id TEXT PRIMARY KEY, campaign_id TEXT REFERENCES campaigns(id), name TEXT NOT NULL,
  evidence_count INTEGER NOT NULL, features_json TEXT NOT NULL, confidence REAL NOT NULL,
  provenance_json TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS research_observations (
  id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL REFERENCES campaigns(id), platform TEXT NOT NULL,
  url TEXT NOT NULL, creator TEXT NOT NULL, observed_at TEXT NOT NULL, published_at TEXT NOT NULL,
  metrics_json TEXT NOT NULL, baseline_json TEXT NOT NULL, raw_json TEXT NOT NULL,
  derived_json TEXT NOT NULL, transcript TEXT, labels_json TEXT NOT NULL,
  UNIQUE(campaign_id, url)
);
CREATE TABLE IF NOT EXISTS trend_clusters (
  id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL REFERENCES campaigns(id), label TEXT NOT NULL,
  metrics_json TEXT NOT NULL, lifecycle_state TEXT NOT NULL, evidence_ids_json TEXT NOT NULL,
  UNIQUE(campaign_id, label)
);
CREATE TABLE IF NOT EXISTS strategy_briefs (
  id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL REFERENCES campaigns(id),
  brief_json TEXT NOT NULL, evidence_ids_json TEXT NOT NULL, created_at TEXT NOT NULL,
  UNIQUE(campaign_id)
);
CREATE TABLE IF NOT EXISTS strategy_policies (
  id TEXT PRIMARY KEY, version INTEGER NOT NULL UNIQUE, weights_json TEXT NOT NULL,
  exploration_pct REAL NOT NULL, active INTEGER NOT NULL, created_at TEXT NOT NULL,
  supersedes_id TEXT REFERENCES strategy_policies(id)
);
CREATE TABLE IF NOT EXISTS candidate_moments (
  id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL REFERENCES campaigns(id),
  source_item_id TEXT NOT NULL REFERENCES source_items(id), start_ms INTEGER NOT NULL,
  end_ms INTEGER NOT NULL, transcript TEXT NOT NULL, discovery_pass TEXT NOT NULL,
  research_match_json TEXT NOT NULL, evidence_ids_json TEXT NOT NULL, scores_json TEXT NOT NULL,
  selection_reason TEXT NOT NULL, saturation_json TEXT NOT NULL, predicted_score REAL NOT NULL,
  policy_id TEXT NOT NULL REFERENCES strategy_policies(id), status TEXT NOT NULL,
  UNIQUE(campaign_id, source_item_id, start_ms, end_ms, discovery_pass)
);
CREATE TABLE IF NOT EXISTS clip_variants (
  id TEXT PRIMARY KEY, candidate_id TEXT NOT NULL REFERENCES candidate_moments(id),
  parent_id TEXT REFERENCES clip_variants(id), style_profile_id TEXT REFERENCES style_profiles(id),
  version INTEGER NOT NULL, render_spec_json TEXT NOT NULL, file_uri TEXT,
  qa_status TEXT NOT NULL, deterministic_qa_json TEXT NOT NULL, ai_qa_json TEXT NOT NULL,
  predicted_score REAL NOT NULL, created_at TEXT NOT NULL,
  UNIQUE(candidate_id, version)
);
CREATE TABLE IF NOT EXISTS notifications (
  id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL REFERENCES campaigns(id),
  notification_type TEXT NOT NULL, idempotency_key TEXT NOT NULL UNIQUE,
  recipient TEXT NOT NULL, file_uri TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reviews (
  id TEXT PRIMARY KEY, clip_variant_id TEXT NOT NULL REFERENCES clip_variants(id),
  decision TEXT NOT NULL, reason_code TEXT, feedback_text TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS edit_requests (
  id TEXT PRIMARY KEY, clip_variant_id TEXT NOT NULL REFERENCES clip_variants(id),
  child_variant_id TEXT REFERENCES clip_variants(id), instruction TEXT NOT NULL,
  parsed_changes_json TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS approvals (
  id TEXT PRIMARY KEY, clip_variant_id TEXT NOT NULL REFERENCES clip_variants(id),
  review_id TEXT NOT NULL REFERENCES reviews(id), approved_at TEXT NOT NULL, revoked_at TEXT,
  UNIQUE(clip_variant_id)
);
CREATE TABLE IF NOT EXISTS connected_accounts (
  id TEXT PRIMARY KEY, platform TEXT NOT NULL, display_name TEXT NOT NULL,
  adapter TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS publications (
  id TEXT PRIMARY KEY, clip_variant_id TEXT NOT NULL REFERENCES clip_variants(id),
  platform TEXT NOT NULL, account_id TEXT, approval_id TEXT NOT NULL REFERENCES approvals(id),
  status TEXT NOT NULL, idempotency_key TEXT NOT NULL UNIQUE, external_post_id TEXT,
  url TEXT, export_uri TEXT, published_at TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS feedback (
  id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL REFERENCES campaigns(id),
  clip_variant_id TEXT, rating INTEGER, reason_code TEXT, feedback_text TEXT,
  human_minutes REAL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS performance_snapshots (
  id TEXT PRIMARY KEY, publication_id TEXT NOT NULL REFERENCES publications(id),
  captured_at TEXT NOT NULL, metrics_json TEXT NOT NULL, revenue_json TEXT NOT NULL,
  account_baseline_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS experiments (
  id TEXT PRIMARY KEY, hypothesis TEXT NOT NULL, control_policy_id TEXT NOT NULL,
  treatment_policy_id TEXT NOT NULL, allocation REAL NOT NULL, status TEXT NOT NULL,
  outcome_json TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS research_ledger (
  id TEXT PRIMARY KEY, campaign_id TEXT, entry_type TEXT NOT NULL,
  finding TEXT NOT NULL, evidence_json TEXT NOT NULL, confidence REAL NOT NULL,
  decision TEXT NOT NULL, applies_to_json TEXT NOT NULL, policy_id TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_log (
  id TEXT PRIMARY KEY, entity_type TEXT NOT NULL, entity_id TEXT NOT NULL,
  action TEXT NOT NULL, details_json TEXT NOT NULL, created_at TEXT NOT NULL
);

