-- Expand own-area catalog type without disabling foreign keys or losing any history.
CREATE TEMP TABLE backup_v21_workspace_ukraine_observations AS SELECT * FROM workspace_ukraine_observations;
DELETE FROM workspace_ukraine_observations;
CREATE TEMP TABLE backup_v21_workspace_ukraine_episodes AS SELECT * FROM workspace_ukraine_episodes;
DELETE FROM workspace_ukraine_episodes;
CREATE TEMP TABLE backup_v21_workspace_ukraine_regions AS SELECT * FROM workspace_ukraine_regions;
DELETE FROM workspace_ukraine_regions;
CREATE TEMP TABLE backup_v21_catalog_object_areas AS SELECT * FROM catalog_object_areas;
DELETE FROM catalog_object_areas;
CREATE TEMP TABLE backup_v21_station_sensors AS SELECT * FROM station_sensors;
DELETE FROM station_sensors;
CREATE TEMP TABLE backup_v21_station_measurements AS SELECT * FROM station_measurements;
DELETE FROM station_measurements;
CREATE TEMP TABLE backup_v21_station_index_observations AS SELECT * FROM station_index_observations;
DELETE FROM station_index_observations;
CREATE TEMP TABLE backup_v21_workspace_watchlist AS SELECT * FROM workspace_watchlist;
DELETE FROM workspace_watchlist;
CREATE TABLE catalog_objects_v21 (
 ref TEXT PRIMARY KEY,
 type TEXT NOT NULL CHECK(type IN ('communication','hydro_station','air_quality_station','area','aircraft','ship','ua_region','civil_alert','custom_area')),
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
INSERT INTO catalog_objects_v21 SELECT * FROM catalog_objects;
DROP TABLE catalog_objects;
ALTER TABLE catalog_objects_v21 RENAME TO catalog_objects;
CREATE INDEX catalog_type_source ON catalog_objects(type,source_id,ref);
CREATE INDEX catalog_label ON catalog_objects(search_text,ref);
CREATE INDEX catalog_publication ON catalog_objects(published_at,ref);
CREATE INDEX catalog_updated ON catalog_objects(updated_at,ref);
CREATE INDEX catalog_validity ON catalog_objects(valid_from,valid_until);
INSERT INTO workspace_watchlist SELECT * FROM backup_v21_workspace_watchlist;
DROP TABLE backup_v21_workspace_watchlist;
INSERT INTO station_index_observations SELECT * FROM backup_v21_station_index_observations;
DROP TABLE backup_v21_station_index_observations;
INSERT INTO station_measurements SELECT * FROM backup_v21_station_measurements;
DROP TABLE backup_v21_station_measurements;
INSERT INTO station_sensors SELECT * FROM backup_v21_station_sensors;
DROP TABLE backup_v21_station_sensors;
INSERT INTO catalog_object_areas SELECT * FROM backup_v21_catalog_object_areas;
DROP TABLE backup_v21_catalog_object_areas;
INSERT INTO workspace_ukraine_regions SELECT * FROM backup_v21_workspace_ukraine_regions;
DROP TABLE backup_v21_workspace_ukraine_regions;
INSERT INTO workspace_ukraine_episodes SELECT * FROM backup_v21_workspace_ukraine_episodes;
DROP TABLE backup_v21_workspace_ukraine_episodes;
INSERT INTO workspace_ukraine_observations SELECT * FROM backup_v21_workspace_ukraine_observations;
DROP TABLE backup_v21_workspace_ukraine_observations;
CREATE INDEX catalog_moving_identity ON catalog_objects(type,native_id);
CREATE TABLE workspace_areas (
 id TEXT PRIMARY KEY,
 name TEXT NOT NULL,
 description TEXT NOT NULL DEFAULT '',
 color TEXT NOT NULL,
 revision INTEGER NOT NULL,
 archived INTEGER NOT NULL CHECK(archived IN (0,1)),
 definition_json TEXT NOT NULL,
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL
);
CREATE TABLE workspace_area_revisions (
 id TEXT NOT NULL REFERENCES workspace_areas(id),
 name TEXT NOT NULL,
 description TEXT NOT NULL DEFAULT '',
 color TEXT NOT NULL,
 revision INTEGER NOT NULL,
 archived INTEGER NOT NULL CHECK(archived IN (0,1)),
 definition_json TEXT NOT NULL,
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 PRIMARY KEY(id,revision)
);
CREATE TRIGGER workspace_area_revisions_immutable BEFORE UPDATE ON workspace_area_revisions
BEGIN SELECT RAISE(ABORT,'Area revision is immutable'); END;
CREATE TABLE workspace_rules (
 id TEXT PRIMARY KEY,
 name TEXT NOT NULL,
 description TEXT NOT NULL,
 template TEXT NOT NULL CHECK(template IN ('transport','measurement','communication','ukraine')),
 mode TEXT NOT NULL CHECK(mode IN ('available','background')),
 enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),
 priority TEXT NOT NULL CHECK(priority IN ('low','normal','high')),
 config_json TEXT NOT NULL,
 revision INTEGER NOT NULL DEFAULT 1,
 checkpoint_id INTEGER NOT NULL DEFAULT 0,
 last_evaluated_at TEXT,
 last_successful_at TEXT,
 condition_state TEXT NOT NULL DEFAULT 'unknown',
 error TEXT,
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL
);
CREATE TABLE workspace_rule_revisions (
 rule_id TEXT NOT NULL REFERENCES workspace_rules(id) ON DELETE CASCADE,
 revision INTEGER NOT NULL,
 payload_json TEXT NOT NULL,
 at TEXT NOT NULL,
 PRIMARY KEY(rule_id,revision)
);
CREATE TABLE workspace_observations (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 observation_key TEXT NOT NULL UNIQUE,
 kind TEXT NOT NULL,
 object_ref TEXT NOT NULL,
 source_id TEXT NOT NULL,
 observed_at TEXT NOT NULL,
 recorded_at TEXT NOT NULL,
 trusted INTEGER NOT NULL,
 payload_json TEXT NOT NULL
);
CREATE INDEX monitor_observations_time ON workspace_observations(observed_at,id);
CREATE INDEX monitor_observations_object ON workspace_observations(kind,object_ref,id);
CREATE TABLE workspace_rule_states (
 rule_id TEXT NOT NULL REFERENCES workspace_rules(id) ON DELETE CASCADE,
 rule_revision INTEGER NOT NULL,
 area_revision INTEGER NOT NULL DEFAULT 0,
 object_ref TEXT NOT NULL,
 state_json TEXT NOT NULL,
 PRIMARY KEY(rule_id,rule_revision,area_revision,object_ref)
);
CREATE TABLE workspace_monitor_meta (
 key TEXT PRIMARY KEY,
 value TEXT NOT NULL
);
-- Evidence and handling are separate. No FK to source histories or rules: retention
-- and rule changes must not remove the explanation of an already detected event.
CREATE TABLE workspace_events (
 id TEXT PRIMARY KEY,
 dedup_key TEXT NOT NULL UNIQUE,
 rule_id TEXT NOT NULL,
 rule_revision INTEGER NOT NULL,
 rule_name TEXT NOT NULL,
 object_ref TEXT NOT NULL,
 object_type TEXT NOT NULL,
 area_id TEXT,
 priority TEXT NOT NULL CHECK(priority IN ('low','normal','high')),
 condition_state TEXT NOT NULL CHECK(condition_state IN ('met','unmet','unknown')),
 description TEXT NOT NULL,
 observed_at TEXT NOT NULL,
 detected_at TEXT NOT NULL,
 evidence_json TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'new' CHECK(status IN ('new','accepted','closed')),
 revision INTEGER NOT NULL DEFAULT 1,
 updated_at TEXT NOT NULL
);
CREATE INDEX workspace_events_inbox ON workspace_events(status,detected_at DESC,id);
CREATE INDEX workspace_events_rule ON workspace_events(rule_id,observed_at,id);
CREATE INDEX workspace_events_area ON workspace_events(area_id,observed_at,id);
CREATE TRIGGER workspace_event_evidence_immutable BEFORE UPDATE ON workspace_events
WHEN NEW.id IS NOT OLD.id OR NEW.dedup_key IS NOT OLD.dedup_key
 OR NEW.rule_id IS NOT OLD.rule_id OR NEW.rule_revision IS NOT OLD.rule_revision
 OR NEW.rule_name IS NOT OLD.rule_name OR NEW.object_ref IS NOT OLD.object_ref
 OR NEW.object_type IS NOT OLD.object_type OR NEW.area_id IS NOT OLD.area_id
 OR NEW.priority IS NOT OLD.priority OR NEW.condition_state IS NOT OLD.condition_state
 OR NEW.description IS NOT OLD.description OR NEW.observed_at IS NOT OLD.observed_at
 OR NEW.detected_at IS NOT OLD.detected_at OR NEW.evidence_json IS NOT OLD.evidence_json
BEGIN SELECT RAISE(ABORT,'Event evidence is immutable'); END;
CREATE TABLE workspace_event_history (
 id INTEGER PRIMARY KEY,
 event_id TEXT NOT NULL REFERENCES workspace_events(id) ON DELETE CASCADE,
 event_revision INTEGER NOT NULL,
 action TEXT NOT NULL CHECK(action IN ('create','status','comment')),
 payload_json TEXT NOT NULL,
 at TEXT NOT NULL,
 UNIQUE(event_id,event_revision)
);
CREATE INDEX workspace_event_history_event ON workspace_event_history(event_id,id);
-- Add event material without reserializing any existing immutable snapshot.
DROP TRIGGER dossier_materials_immutable;
ALTER TABLE workspace_dossier_materials RENAME TO workspace_dossier_materials_v20;
CREATE TABLE workspace_dossier_materials (
 id TEXT PRIMARY KEY,
 dossier_id TEXT NOT NULL REFERENCES workspace_dossiers(id) ON DELETE CASCADE,
 title TEXT NOT NULL,
 kind TEXT NOT NULL CHECK(kind IN ('object','timeline','comparison','graph','event')),
 object_ref TEXT,
 captured_at TEXT NOT NULL,
 sha256 TEXT NOT NULL,
 byte_size INTEGER NOT NULL,
 snapshot_json TEXT NOT NULL
);
INSERT INTO workspace_dossier_materials SELECT * FROM workspace_dossier_materials_v20;
DROP TABLE workspace_dossier_materials_v20;
CREATE INDEX dossier_materials_parent ON workspace_dossier_materials(dossier_id,captured_at,id);
CREATE TRIGGER dossier_materials_immutable BEFORE UPDATE ON workspace_dossier_materials
BEGIN SELECT RAISE(ABORT,'Saved analysis material is immutable'); END;
