-- Local, on-demand observations. Every correction is an immutable revision.
CREATE TABLE station_sensors (
    sensor_id TEXT PRIMARY KEY,
    object_ref TEXT NOT NULL REFERENCES catalog_objects(ref),
    parameter TEXT NOT NULL,
    name TEXT NOT NULL,
    unit TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    fetched_at TEXT NOT NULL
);
CREATE INDEX station_sensors_object ON station_sensors(object_ref, parameter, sensor_id);

CREATE TABLE station_measurements (
    id INTEGER PRIMARY KEY,
    object_ref TEXT NOT NULL REFERENCES catalog_objects(ref),
    sensor_id TEXT NOT NULL DEFAULT '',
    metric TEXT NOT NULL,
    observed_key TEXT NOT NULL,
    observed_at TEXT,
    source_time TEXT,
    value REAL,
    unit TEXT,
    fetched_at TEXT NOT NULL,
    first_fetched_at TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision > 0),
    is_current INTEGER NOT NULL DEFAULT 1 CHECK (is_current IN (0,1)),
    quality TEXT NOT NULL CHECK (quality IN ('valid','unknown_time','future')),
    content_hash TEXT NOT NULL,
    provenance_json TEXT NOT NULL DEFAULT '{}',
    thresholds_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE(object_ref, sensor_id, metric, observed_key, revision)
);
CREATE INDEX station_measurements_series
    ON station_measurements(object_ref, sensor_id, metric, observed_at, revision DESC);
CREATE INDEX station_measurements_window ON station_measurements(observed_at, object_ref);
CREATE INDEX station_measurements_latest ON station_measurements(object_ref, observed_at DESC, revision DESC);
CREATE INDEX station_measurements_metric_latest
    ON station_measurements(object_ref, metric, observed_at DESC, revision DESC);
CREATE INDEX station_measurements_current_window ON station_measurements(observed_at, object_ref)
    WHERE is_current=1 AND quality='valid';
CREATE INDEX station_measurements_invalid_retention ON station_measurements(first_fetched_at)
    WHERE quality!='valid';

CREATE TABLE station_index_observations (
    id INTEGER PRIMARY KEY,
    object_ref TEXT NOT NULL REFERENCES catalog_objects(ref),
    observed_key TEXT NOT NULL,
    observed_at TEXT,
    source_time TEXT,
    calculated_at TEXT,
    source_calculated_time TEXT,
    value INTEGER,
    name TEXT,
    fetched_at TEXT NOT NULL,
    first_fetched_at TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision > 0),
    is_current INTEGER NOT NULL DEFAULT 1 CHECK (is_current IN (0,1)),
    quality TEXT NOT NULL CHECK (quality IN ('valid','unknown_time','future')),
    content_hash TEXT NOT NULL,
    provenance_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE(object_ref, observed_key, revision)
);
CREATE INDEX station_index_series ON station_index_observations(object_ref, observed_at, revision DESC);
CREATE INDEX station_index_current_window ON station_index_observations(observed_at, object_ref)
    WHERE is_current=1 AND quality='valid';
CREATE INDEX station_index_retention ON station_index_observations(observed_at) WHERE quality='valid';
CREATE INDEX station_index_invalid_retention ON station_index_observations(first_fetched_at)
    WHERE quality!='valid';

-- Only a hash and first-seen clock survive invalid-time expiry: repeated copies
-- of an undated/far-future observation must not renew its fourteen-day lifetime.
CREATE TABLE station_observation_keys (
    key_hash TEXT PRIMARY KEY,
    first_fetched_at TEXT NOT NULL
);

CREATE TABLE workspace_source_runs (
    id INTEGER PRIMARY KEY,
    resource TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    status TEXT NOT NULL,
    item_count INTEGER NOT NULL DEFAULT 0,
    rejected_count INTEGER NOT NULL DEFAULT 0,
    complete INTEGER NOT NULL DEFAULT 0,
    message TEXT NOT NULL DEFAULT ''
);
CREATE INDEX workspace_source_runs_resource ON workspace_source_runs(resource, fetched_at DESC, id DESC);
