-- Independent measurements; retired observation/editorial tables remain untouched.
CREATE TABLE ioda_entities (
 entity_type TEXT NOT NULL, entity_code TEXT NOT NULL, name TEXT NOT NULL,
 metadata_json TEXT NOT NULL, verified_at TEXT NOT NULL,
 PRIMARY KEY(entity_type, entity_code)
);
CREATE TABLE ioda_events (
 id TEXT PRIMARY KEY, entity_type TEXT NOT NULL, entity_code TEXT NOT NULL,
 name TEXT NOT NULL, datasource TEXT NOT NULL, method TEXT NOT NULL,
 started_at INTEGER NOT NULL, source_until INTEGER NOT NULL, ended_at INTEGER,
 score REAL NOT NULL, measured_at INTEGER NOT NULL,
 raw_json TEXT NOT NULL, provenance_json TEXT NOT NULL,
 first_seen_at TEXT NOT NULL, fetched_at TEXT NOT NULL, synthetic INTEGER NOT NULL DEFAULT 0,
 UNIQUE(entity_type,entity_code,datasource,method,started_at)
);
CREATE INDEX ioda_event_window ON ioda_events(started_at,ended_at);
CREATE TABLE ioda_alerts (
 id TEXT PRIMARY KEY, entity_type TEXT NOT NULL, entity_code TEXT NOT NULL,
 datasource TEXT NOT NULL, method TEXT NOT NULL, measured_at INTEGER NOT NULL,
 raw_json TEXT NOT NULL, provenance_json TEXT NOT NULL, fetched_at TEXT NOT NULL
);
CREATE TABLE ioda_samples (
 entity_type TEXT NOT NULL, entity_code TEXT NOT NULL, datasource TEXT NOT NULL,
 measured_at INTEGER NOT NULL, step INTEGER NOT NULL, native_step INTEGER NOT NULL,
 value REAL, fetched_at TEXT NOT NULL, provenance_json TEXT NOT NULL,
 PRIMARY KEY(entity_type,entity_code,datasource,measured_at,step)
);
CREATE INDEX ioda_sample_window ON ioda_samples(measured_at);
