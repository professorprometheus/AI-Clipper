CREATE TABLE IF NOT EXISTS campaign_accounts (
  campaign_id TEXT NOT NULL REFERENCES campaigns(id),
  account_id TEXT NOT NULL REFERENCES connected_accounts(id),
  created_at TEXT NOT NULL,
  PRIMARY KEY(campaign_id, account_id)
);

