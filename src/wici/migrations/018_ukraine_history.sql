-- Expand the catalogue CHECK inside one transaction while preserving all child rows.
-- foreign_keys stays enabled. Temporary copies prevent cascades/data loss on rebuild.
CREATE TEMP TABLE backup_v18_catalog_object_areas AS SELECT * FROM catalog_object_areas;
DELETE FROM catalog_object_areas;
CREATE TEMP TABLE backup_v18_station_sensors AS SELECT * FROM station_sensors;
DELETE FROM station_sensors;
CREATE TEMP TABLE backup_v18_station_measurements AS SELECT * FROM station_measurements;
DELETE FROM station_measurements;
CREATE TEMP TABLE backup_v18_station_index_observations AS SELECT * FROM station_index_observations;
DELETE FROM station_index_observations;
CREATE TEMP TABLE backup_v18_watchlist AS SELECT * FROM workspace_watchlist;
DELETE FROM workspace_watchlist;
CREATE TABLE catalog_objects_v18 (
 ref TEXT PRIMARY KEY,
 type TEXT NOT NULL CHECK(type IN ('communication','hydro_station','air_quality_station','area','aircraft','ship','ua_region','civil_alert')),
 source_id TEXT NOT NULL,
 native_id TEXT NOT NULL,
 label TEXT NOT NULL,
 search_text TEXT NOT NULL,
 latitude REAL,
 longitude REAL,
 published_at TEXT,
 updated_at TEXT,
 valid_from TEXT,
 valid_until TEXT,
 display_from TEXT,
 display_until TEXT,
 date_precision TEXT NOT NULL DEFAULT 'instant',
 document_id INTEGER REFERENCES documents(id),
 document_version_id INTEGER REFERENCES document_versions(id),
 metadata_json TEXT NOT NULL DEFAULT '{}',
 projection_version INTEGER NOT NULL DEFAULT 1,
 revision INTEGER NOT NULL DEFAULT 1
);
INSERT INTO catalog_objects_v18 SELECT * FROM catalog_objects;
DROP TABLE catalog_objects;
ALTER TABLE catalog_objects_v18 RENAME TO catalog_objects;
CREATE INDEX catalog_type_source ON catalog_objects(type,source_id,ref);
CREATE INDEX catalog_label ON catalog_objects(search_text,ref);
CREATE INDEX catalog_publication ON catalog_objects(published_at,ref);
CREATE INDEX catalog_updated ON catalog_objects(updated_at,ref);
CREATE INDEX catalog_validity ON catalog_objects(valid_from,valid_until);
INSERT INTO catalog_object_areas SELECT * FROM backup_v18_catalog_object_areas;
DROP TABLE backup_v18_catalog_object_areas;
INSERT INTO station_sensors SELECT * FROM backup_v18_station_sensors;
DROP TABLE backup_v18_station_sensors;
INSERT INTO station_measurements SELECT * FROM backup_v18_station_measurements;
DROP TABLE backup_v18_station_measurements;
INSERT INTO station_index_observations SELECT * FROM backup_v18_station_index_observations;
DROP TABLE backup_v18_station_index_observations;

INSERT INTO workspace_watchlist SELECT * FROM backup_v18_watchlist;
DROP TABLE backup_v18_watchlist;
CREATE INDEX catalog_moving_identity ON catalog_objects(type,native_id);

CREATE TABLE workspace_ukraine_state (
 id INTEGER PRIMARY KEY CHECK(id=1),
 recording INTEGER NOT NULL DEFAULT 0,
 recording_since TEXT,
 status TEXT NOT NULL DEFAULT 'not_loaded',
 fetched_at TEXT,
 source_updated_at TEXT,
 source_version TEXT,
 last_successful_at TEXT,
 last_recorded_at TEXT,
 gap_reason TEXT,
 updated_at TEXT
);
INSERT INTO workspace_ukraine_state(id) VALUES(1);
CREATE TABLE workspace_ukraine_regions (
 ref TEXT PRIMARY KEY REFERENCES catalog_objects(ref) ON DELETE CASCADE,
 scope TEXT NOT NULL CHECK(scope IN ('oblast','raion')),
 native_key TEXT NOT NULL,
 label TEXT NOT NULL,
 oblast TEXT,
 parent_ref TEXT,
 parent_basis TEXT,
 geometry_json TEXT,
 geometry_fetched_at TEXT,
 current_state TEXT NOT NULL DEFAULT 'unknown',
 source_since TEXT,
 source_updated_at TEXT,
 fetched_at TEXT,
 first_seen_at TEXT NOT NULL,
 UNIQUE(scope,native_key)
);
CREATE TABLE workspace_ukraine_episodes (
 ref TEXT PRIMARY KEY REFERENCES catalog_objects(ref) ON DELETE CASCADE,
 region_ref TEXT NOT NULL REFERENCES workspace_ukraine_regions(ref),
 first_seen_at TEXT NOT NULL,
 last_seen_at TEXT NOT NULL,
 source_since TEXT,
 source_updated_at TEXT,
 ended_after TEXT,
 ended_before TEXT,
 active INTEGER NOT NULL DEFAULT 1,
 level TEXT NOT NULL,
 reasons_json TEXT NOT NULL DEFAULT '[]'
);
CREATE INDEX ukraine_episodes_region ON workspace_ukraine_episodes(region_ref,first_seen_at);
CREATE UNIQUE INDEX ukraine_episodes_active ON workspace_ukraine_episodes(region_ref) WHERE active=1;
CREATE TABLE workspace_ukraine_runs (
 id INTEGER PRIMARY KEY,
 observed_at TEXT NOT NULL,
 fetched_at TEXT,
 recorded_at TEXT NOT NULL,
 status TEXT NOT NULL,
 source_updated_at TEXT,
 source_version TEXT,
 reason TEXT
);
CREATE INDEX ukraine_runs_time ON workspace_ukraine_runs(observed_at,id);
CREATE UNIQUE INDEX ukraine_runs_success ON workspace_ukraine_runs(fetched_at) WHERE status='ready';
CREATE TABLE workspace_ukraine_observations (
 id INTEGER PRIMARY KEY,
 run_id INTEGER NOT NULL REFERENCES workspace_ukraine_runs(id),
 region_ref TEXT NOT NULL REFERENCES workspace_ukraine_regions(ref),
 episode_ref TEXT REFERENCES workspace_ukraine_episodes(ref),
 observed_at TEXT NOT NULL,
 state TEXT NOT NULL CHECK(state IN ('red','yellow','none')),
 source_since TEXT,
 source_updated_at TEXT,
 reasons_json TEXT NOT NULL DEFAULT '[]'
);
CREATE INDEX ukraine_observations_region ON workspace_ukraine_observations(region_ref,observed_at,id);
CREATE INDEX ukraine_observations_time ON workspace_ukraine_observations(observed_at,region_ref,episode_ref);
