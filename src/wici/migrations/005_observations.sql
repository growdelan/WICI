CREATE TABLE observation_stations (
 source_id TEXT NOT NULL, station_id TEXT NOT NULL, metadata_json TEXT NOT NULL,
 updated_at TEXT NOT NULL, PRIMARY KEY(source_id,station_id)
);
CREATE TABLE observations (
 source_id TEXT NOT NULL, station_id TEXT NOT NULL, parameter TEXT NOT NULL,
 observation_key TEXT NOT NULL, observed_at TEXT, published_at TEXT, fetched_at TEXT NOT NULL,
 value REAL, unit TEXT NOT NULL, quality TEXT NOT NULL, metadata_json TEXT NOT NULL DEFAULT '{}',
 PRIMARY KEY(source_id,station_id,parameter,observation_key)
);
CREATE INDEX observations_series ON observations(source_id,station_id,parameter,observed_at);
CREATE INDEX observations_retention ON observations(fetched_at);
CREATE TABLE observation_snapshots (
 source_id TEXT PRIMARY KEY, fetched_at TEXT NOT NULL, payload_json TEXT NOT NULL
);
CREATE TABLE earth_products (
 source_id TEXT NOT NULL, product_id TEXT NOT NULL, version TEXT NOT NULL DEFAULT '',
 observed_at TEXT, observation_end TEXT, published_at TEXT, fetched_at TEXT NOT NULL,
 metadata_json TEXT NOT NULL, PRIMARY KEY(source_id,product_id,version)
);
CREATE INDEX earth_products_time ON earth_products(source_id,observed_at);
CREATE TABLE persistent_cache (
 namespace TEXT NOT NULL, cache_key TEXT NOT NULL, body BLOB NOT NULL, media_type TEXT NOT NULL,
 expires_at TEXT NOT NULL, touched_at TEXT NOT NULL, size_bytes INTEGER NOT NULL,
 PRIMARY KEY(namespace,cache_key)
);
CREATE INDEX persistent_cache_expiry ON persistent_cache(expires_at);
CREATE INDEX persistent_cache_lru ON persistent_cache(touched_at);
CREATE TABLE api_usage (
 provider TEXT NOT NULL, month TEXT NOT NULL, requests INTEGER NOT NULL DEFAULT 0,
 processing_units REAL NOT NULL DEFAULT 0, PRIMARY KEY(provider,month)
);
