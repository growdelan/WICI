CREATE TABLE model_decisions (
 id INTEGER PRIMARY KEY,
 review_id INTEGER NOT NULL UNIQUE REFERENCES review_items(id),
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
 probabilities_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX model_decisions_day ON model_decisions(budget_day);
