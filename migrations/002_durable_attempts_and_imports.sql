ALTER TABLE pipeline_jobs ADD COLUMN available_at TEXT;

CREATE TABLE IF NOT EXISTS pipeline_stage_attempts (
  id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL REFERENCES pipeline_jobs(id),
  stage TEXT NOT NULL,
  status TEXT NOT NULL,
  attempt INTEGER NOT NULL,
  worker_token TEXT NOT NULL,
  output_json TEXT NOT NULL,
  started_at TEXT NOT NULL,
  heartbeat_count INTEGER NOT NULL DEFAULT 0,
  completed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_stage_attempts_job_stage
  ON pipeline_stage_attempts(job_id, stage, started_at);

CREATE TABLE IF NOT EXISTS source_imports (
  id TEXT PRIMARY KEY,
  approved_source_id TEXT NOT NULL UNIQUE REFERENCES approved_sources(id),
  media_uri TEXT NOT NULL,
  media_sha256 TEXT NOT NULL,
  original_filename TEXT NOT NULL,
  content_type TEXT NOT NULL,
  transcript_json TEXT NOT NULL,
  rights_attestation TEXT NOT NULL,
  rights_attested_at TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_source_imports_sha256 ON source_imports(media_sha256);

