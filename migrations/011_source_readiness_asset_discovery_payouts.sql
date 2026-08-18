ALTER TABLE campaigns ADD COLUMN payout_amount REAL;
ALTER TABLE campaigns ADD COLUMN views_per_payout_unit INTEGER;
ALTER TABLE campaigns ADD COLUMN payout_rules_json TEXT NOT NULL DEFAULT '{}';
UPDATE campaigns SET payout_amount=COALESCE(payout_amount,payout_value,0);
UPDATE campaigns SET views_per_payout_unit=COALESCE(views_per_payout_unit,1);

ALTER TABLE approved_sources ADD COLUMN pasted_transcript_json TEXT;
ALTER TABLE approved_sources ADD COLUMN transcript_timestamped INTEGER NOT NULL DEFAULT 0;

ALTER TABLE assets ADD COLUMN provider TEXT;
ALTER TABLE assets ADD COLUMN provider_asset_id TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS idx_assets_provider_identity
  ON assets(provider, provider_asset_id);
