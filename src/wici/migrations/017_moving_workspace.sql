-- Expand the catalogue CHECK inside one transaction while preserving all child rows.
-- foreign_keys stays enabled. Temporary copies prevent cascades/data loss on rebuild.
CREATE TEMP TABLE backup_v17_catalog_object_areas AS SELECT * FROM catalog_object_areas;
DELETE FROM catalog_object_areas;
CREATE TEMP TABLE backup_v17_station_sensors AS SELECT * FROM station_sensors;
DELETE FROM station_sensors;
CREATE TEMP TABLE backup_v17_station_measurements AS SELECT * FROM station_measurements;
DELETE FROM station_measurements;
CREATE TEMP TABLE backup_v17_station_index_observations AS SELECT * FROM station_index_observations;
DELETE FROM station_index_observations;
CREATE TABLE catalog_objects_v17 (
 ref TEXT PRIMARY KEY,
 type TEXT NOT NULL CHECK(type IN ('communication','hydro_station','air_quality_station','area','aircraft','ship')),
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
INSERT INTO catalog_objects_v17 SELECT * FROM catalog_objects;
DROP TABLE catalog_objects;
ALTER TABLE catalog_objects_v17 RENAME TO catalog_objects;
CREATE INDEX catalog_type_source ON catalog_objects(type,source_id,ref);
CREATE INDEX catalog_label ON catalog_objects(search_text,ref);
CREATE INDEX catalog_publication ON catalog_objects(published_at,ref);
CREATE INDEX catalog_updated ON catalog_objects(updated_at,ref);
CREATE INDEX catalog_validity ON catalog_objects(valid_from,valid_until);
INSERT INTO catalog_object_areas SELECT * FROM backup_v17_catalog_object_areas;
DROP TABLE backup_v17_catalog_object_areas;
INSERT INTO station_sensors SELECT * FROM backup_v17_station_sensors;
DROP TABLE backup_v17_station_sensors;
INSERT INTO station_measurements SELECT * FROM backup_v17_station_measurements;
DROP TABLE backup_v17_station_measurements;
INSERT INTO station_index_observations SELECT * FROM backup_v17_station_index_observations;
DROP TABLE backup_v17_station_index_observations;

CREATE TABLE workspace_watchlist (
 ref TEXT PRIMARY KEY REFERENCES catalog_objects(ref) ON DELETE CASCADE,
 created_at TEXT NOT NULL
);
CREATE TABLE workspace_moving_sources (
 resource TEXT PRIMARY KEY,
 status TEXT NOT NULL,
 stale INTEGER NOT NULL,
 fetched_at TEXT,
 item_count INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX object_tracks_identity ON object_tracks(kind,object_id,started_at);
CREATE INDEX object_track_points_time ON object_track_points(position_at,track_id);
CREATE INDEX catalog_moving_identity ON catalog_objects(type,native_id);
