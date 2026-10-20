CREATE TABLE model_decisions_v3 (
 id INTEGER PRIMARY KEY,
 review_id INTEGER NOT NULL REFERENCES review_items(id),
 document_version_id INTEGER NOT NULL REFERENCES document_versions(id),
 review_version INTEGER NOT NULL,
 created_at TEXT NOT NULL,
 finished_at TEXT,
 budget_day TEXT NOT NULL,
 model TEXT NOT NULL,
 min_probability REAL NOT NULL DEFAULT 0.98,
 status TEXT NOT NULL,
 reason TEXT NOT NULL DEFAULT '',
 reserved_input_units INTEGER NOT NULL DEFAULT 0,
 input_tokens INTEGER,
 probabilities_json TEXT NOT NULL DEFAULT '{}',
 policy_version TEXT NOT NULL DEFAULT 'v1',
 evaluated_proposal_json TEXT,
 input_hash TEXT,
 UNIQUE(review_id,policy_version)
);
INSERT INTO model_decisions_v3(id,review_id,document_version_id,review_version,created_at,finished_at,budget_day,model,min_probability,status,reason,reserved_input_units,input_tokens,probabilities_json)
 SELECT id,review_id,document_version_id,review_version,created_at,finished_at,budget_day,model,min_probability,status,reason,reserved_input_units,input_tokens,probabilities_json FROM model_decisions;
DROP TABLE model_decisions;
ALTER TABLE model_decisions_v3 RENAME TO model_decisions;
CREATE INDEX model_decisions_day ON model_decisions(budget_day);
