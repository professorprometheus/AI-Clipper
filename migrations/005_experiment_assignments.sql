CREATE TABLE IF NOT EXISTS experiment_assignments (
  id TEXT PRIMARY KEY,
  experiment_id TEXT NOT NULL REFERENCES experiments(id),
  candidate_id TEXT NOT NULL REFERENCES candidate_moments(id),
  arm TEXT NOT NULL CHECK(arm IN ('control','treatment')),
  policy_id TEXT NOT NULL REFERENCES strategy_policies(id),
  assigned_at TEXT NOT NULL,
  UNIQUE(experiment_id, candidate_id)
);
CREATE INDEX IF NOT EXISTS idx_experiment_assignments_arm
  ON experiment_assignments(experiment_id, arm);

