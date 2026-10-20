CREATE TABLE object_tracks (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('aircraft', 'ship')),
    object_id TEXT NOT NULL,
    label TEXT NOT NULL,
    active INTEGER NOT NULL CHECK (active IN (0, 1)),
    started_at TEXT NOT NULL,
    stopped_at TEXT,
    status TEXT NOT NULL,
    message TEXT NOT NULL DEFAULT '',
    pending_break INTEGER NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX object_tracks_active ON object_tracks(kind, object_id) WHERE active = 1;
CREATE TABLE object_track_points (
    track_id TEXT NOT NULL REFERENCES object_tracks(id) ON DELETE CASCADE,
    position_at TEXT NOT NULL,
    latitude REAL NOT NULL,
    longitude REAL NOT NULL,
    altitude_m REAL,
    speed_kmh REAL,
    heading REAL,
    break_before INTEGER NOT NULL CHECK (break_before IN (0, 1)),
    recorded_at TEXT NOT NULL,
    PRIMARY KEY (track_id, position_at)
);
CREATE INDEX object_track_points_retention ON object_track_points(recorded_at);
