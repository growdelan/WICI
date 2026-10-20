CREATE TABLE night_light_regions (
 region_id TEXT PRIMARY KEY, label TEXT NOT NULL, bbox_json TEXT NOT NULL,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE night_light_imports (
 region_id TEXT NOT NULL, granule_id TEXT NOT NULL, sha256 TEXT NOT NULL,
 observation_date TEXT NOT NULL, imported_at TEXT NOT NULL,
 metadata_json TEXT NOT NULL, summary_json TEXT NOT NULL,
 PRIMARY KEY(region_id,granule_id),
 FOREIGN KEY(region_id) REFERENCES night_light_regions(region_id)
);
CREATE TABLE night_light_pixels (
 region_id TEXT NOT NULL, observation_date TEXT NOT NULL, pixel_id TEXT NOT NULL,
 latitude REAL NOT NULL, longitude REAL NOT NULL, corrected_radiance REAL,
 valid INTEGER NOT NULL CHECK(valid IN (0,1)), gap_filled_radiance REAL,
 latest_hq_age_days INTEGER, mandatory_qa INTEGER NOT NULL, cloud_mask INTEGER NOT NULL,
 snow_flag INTEGER NOT NULL, reasons_json TEXT NOT NULL, algorithm_version TEXT NOT NULL,
 method_version TEXT NOT NULL, granule_id TEXT NOT NULL,
 PRIMARY KEY(region_id,observation_date,pixel_id),
 FOREIGN KEY(region_id) REFERENCES night_light_regions(region_id)
);
CREATE INDEX night_light_series ON night_light_pixels(region_id,pixel_id,observation_date);
CREATE TABLE night_light_baseline (
 region_id TEXT NOT NULL, pixel_id TEXT NOT NULL, observation_date TEXT NOT NULL,
 radiance REAL NOT NULL, algorithm_version TEXT NOT NULL, method_version TEXT NOT NULL,
 PRIMARY KEY(region_id,pixel_id,observation_date),
 FOREIGN KEY(region_id) REFERENCES night_light_regions(region_id)
);
CREATE INDEX night_light_baseline_time ON night_light_baseline(region_id,observation_date);
CREATE TABLE night_light_daily (
 region_id TEXT NOT NULL, observation_date TEXT NOT NULL,
 summary_json TEXT NOT NULL, imported_at TEXT NOT NULL,
 PRIMARY KEY(region_id,observation_date),
 FOREIGN KEY(region_id) REFERENCES night_light_regions(region_id)
);
