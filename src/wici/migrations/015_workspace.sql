-- Additive analytical projection. Original publisher records remain authoritative.
CREATE TABLE catalog_objects (
 ref TEXT PRIMARY KEY,
 type TEXT NOT NULL CHECK(type IN ('communication','hydro_station','air_quality_station','area')),
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
CREATE INDEX catalog_type_source ON catalog_objects(type,source_id,ref);
CREATE INDEX catalog_label ON catalog_objects(search_text,ref);
CREATE INDEX catalog_publication ON catalog_objects(published_at,ref);
CREATE INDEX catalog_updated ON catalog_objects(updated_at,ref);
CREATE INDEX catalog_validity ON catalog_objects(valid_from,valid_until);
CREATE TABLE catalog_object_areas (
 ref TEXT NOT NULL REFERENCES catalog_objects(ref) ON DELETE CASCADE,
 admin_code TEXT NOT NULL,
 role TEXT NOT NULL,
 basis TEXT NOT NULL,
 PRIMARY KEY(ref,admin_code,role)
);
CREATE INDEX catalog_area_lookup ON catalog_object_areas(admin_code,ref);
CREATE TABLE workspace_meta (key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE workspace_views (
 id TEXT PRIMARY KEY,
 name TEXT NOT NULL,
 schema_version INTEGER NOT NULL,
 config_json TEXT NOT NULL,
 revision INTEGER NOT NULL DEFAULT 1,
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL
);
