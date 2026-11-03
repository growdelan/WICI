-- Infrastructure keeps its own provenance; existing histories are untouched.
CREATE TABLE infrastructure_objects (
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
CREATE INDEX infrastructure_objects_category ON infrastructure_objects(category);
CREATE INDEX infrastructure_objects_bounds ON infrastructure_objects(min_lon,max_lon,min_lat,max_lat);
CREATE TABLE infrastructure_fetches (
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
CREATE TABLE infrastructure_analyses (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    basis TEXT NOT NULL,
    result_json TEXT NOT NULL,
    sha256 TEXT NOT NULL
);
CREATE TRIGGER infrastructure_analyses_immutable BEFORE UPDATE ON infrastructure_analyses
BEGIN SELECT RAISE(ABORT,'Saved infrastructure analysis is immutable'); END;
