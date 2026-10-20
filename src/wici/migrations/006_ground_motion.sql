CREATE TABLE egms_imports (
 source_id TEXT PRIMARY KEY,
 filename TEXT NOT NULL,
 sha256 TEXT NOT NULL,
 release TEXT NOT NULL,
 version INTEGER NOT NULL,
 period_start TEXT NOT NULL,
 period_end TEXT NOT NULL,
 production_date TEXT,
 imported_at TEXT NOT NULL,
 bbox_json TEXT NOT NULL,
 point_count INTEGER NOT NULL
);
CREATE TABLE egms_points (
 row_id INTEGER PRIMARY KEY,
 point_id TEXT NOT NULL UNIQUE,
 source_id TEXT NOT NULL REFERENCES egms_imports(source_id) ON DELETE CASCADE,
 pid TEXT NOT NULL,
 longitude REAL NOT NULL,
 latitude REAL NOT NULL,
 easting REAL NOT NULL,
 northing REAL NOT NULL,
 mean_velocity REAL,
 mean_velocity_std REAL,
 rmse REAL,
 height REAL,
 series_json TEXT NOT NULL,
 quality_json TEXT NOT NULL,
 UNIQUE(source_id,pid)
);
CREATE INDEX egms_points_source ON egms_points(source_id);
CREATE VIRTUAL TABLE egms_spatial USING rtree(row_id,min_lon,max_lon,min_lat,max_lat);
CREATE TRIGGER egms_spatial_insert AFTER INSERT ON egms_points BEGIN
 INSERT INTO egms_spatial VALUES(new.row_id,new.longitude,new.longitude,new.latitude,new.latitude);
END;
CREATE TRIGGER egms_spatial_delete AFTER DELETE ON egms_points BEGIN
 DELETE FROM egms_spatial WHERE row_id=old.row_id;
END;
CREATE TRIGGER egms_spatial_update AFTER UPDATE OF latitude,longitude ON egms_points BEGIN
 DELETE FROM egms_spatial WHERE row_id=old.row_id;
 INSERT INTO egms_spatial VALUES(new.row_id,new.longitude,new.longitude,new.latitude,new.latitude);
END;
