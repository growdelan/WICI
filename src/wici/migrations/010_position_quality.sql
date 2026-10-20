CREATE TABLE position_quality_samples (
    minute INTEGER NOT NULL,
    aircraft TEXT NOT NULL,
    observed REAL NOT NULL,
    cell TEXT,
    province TEXT,
    eligible INTEGER NOT NULL,
    degraded INTEGER,
    context INTEGER NOT NULL,
    fields TEXT NOT NULL,
    PRIMARY KEY (minute, aircraft)
);
CREATE INDEX position_quality_time ON position_quality_samples(observed);
CREATE TABLE position_quality_source (id INTEGER PRIMARY KEY CHECK(id=1), started REAL,
    attempt REAL, success REAL, status TEXT NOT NULL);
