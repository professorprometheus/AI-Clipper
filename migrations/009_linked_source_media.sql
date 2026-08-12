CREATE TABLE IF NOT EXISTS linked_source_media (
  id TEXT PRIMARY KEY,
  approved_source_id TEXT NOT NULL REFERENCES approved_sources(id),
  external_id TEXT NOT NULL,
  media_uri TEXT NOT NULL,
  media_sha256 TEXT NOT NULL,
  original_filename TEXT NOT NULL,
  content_type TEXT NOT NULL,
  transcript_json TEXT NOT NULL,
  rights_attestation TEXT NOT NULL,
  rights_attested_at TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(approved_source_id, external_id)
);
CREATE INDEX IF NOT EXISTS idx_linked_source_media_sha256
  ON linked_source_media(media_sha256);
