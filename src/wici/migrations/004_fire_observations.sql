CREATE TABLE fire_observations (
    id TEXT PRIMARY KEY,
    product TEXT NOT NULL,
    satellite TEXT NOT NULL,
    instrument TEXT NOT NULL,
    latitude REAL NOT NULL,
    longitude REAL NOT NULL,
    observed_at TEXT NOT NULL,
    confidence TEXT NOT NULL,
    frp REAL NOT NULL,
    voivodeship TEXT NOT NULL,
    voivodeship_name TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL
);
CREATE INDEX fire_observations_time ON fire_observations(observed_at);
