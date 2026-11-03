-- Two development branches used schema versions 22–23 for different infrastructure layouts.
-- Keep the alternate tables and exposure snapshots; add only the Atlas objects missing there.
-- Infrastructure keeps its own provenance; existing histories are untouched.
CREATE TABLE IF NOT EXISTS infrastructure_objects (
    id TEXT PRIMARY KEY,
    category TEXT NOT NULL CHECK(category IN ('road','rail','bridge','health','water','utility')),
    label TEXT NOT NULL,
    source TEXT NOT NULL,
    source_url TEXT,
    source_updated_at TEXT,
    fetched_at TEXT NOT NULL,
    geometry_json TEXT,
    properties_json TEXT NOT NULL,
    min_lon REAL,
    min_lat REAL,
    max_lon REAL,
    max_lat REAL,
    synthetic INTEGER NOT NULL DEFAULT 0 CHECK(synthetic IN (0,1))
);
CREATE INDEX IF NOT EXISTS infrastructure_objects_category ON infrastructure_objects(category);
CREATE INDEX IF NOT EXISTS infrastructure_objects_bounds ON infrastructure_objects(min_lon,max_lon,min_lat,max_lat);
CREATE TABLE IF NOT EXISTS infrastructure_fetches (
    key TEXT PRIMARY KEY,
    bbox_json TEXT NOT NULL,
    categories_json TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    source_updated_at TEXT,
    status TEXT NOT NULL,
    item_count INTEGER NOT NULL,
    skipped_count INTEGER NOT NULL,
    message TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS infrastructure_analyses (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    basis TEXT NOT NULL,
    result_json TEXT NOT NULL,
    sha256 TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS infrastructure_analyses_immutable BEFORE UPDATE ON infrastructure_analyses
BEGIN SELECT RAISE(ABORT,'Saved infrastructure analysis is immutable'); END;

-- Preserve the exact bytes and hashes of every previously saved material.
DROP TRIGGER dossier_materials_immutable;
ALTER TABLE workspace_dossier_materials RENAME TO workspace_dossier_materials_v23_compat;
CREATE TABLE workspace_dossier_materials (
 id TEXT PRIMARY KEY,
 dossier_id TEXT NOT NULL REFERENCES workspace_dossiers(id) ON DELETE CASCADE,
 title TEXT NOT NULL,
 kind TEXT NOT NULL CHECK(kind IN ('object','timeline','comparison','graph','event','exposure','infrastructure')),
 object_ref TEXT,
 captured_at TEXT NOT NULL,
 sha256 TEXT NOT NULL,
 byte_size INTEGER NOT NULL,
 snapshot_json TEXT NOT NULL
);
INSERT INTO workspace_dossier_materials SELECT * FROM workspace_dossier_materials_v23_compat;
DROP TABLE workspace_dossier_materials_v23_compat;
CREATE INDEX dossier_materials_parent ON workspace_dossier_materials(dossier_id,captured_at,id);
CREATE TRIGGER dossier_materials_immutable BEFORE UPDATE ON workspace_dossier_materials
BEGIN SELECT RAISE(ABORT,'Saved analysis material is immutable'); END;
