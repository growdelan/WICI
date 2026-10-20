-- Previous versions did not record provenance; do not guess which provider supplied a row.
CREATE TABLE position_quality_epochs (
    epoch INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL,
    endpoint TEXT NOT NULL
);
INSERT INTO position_quality_epochs VALUES(0, 'Nieustalone źródło (historia sprzed migracji)', '');
ALTER TABLE position_quality_samples RENAME TO position_quality_samples_legacy;
DROP INDEX position_quality_time;
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
    epoch INTEGER NOT NULL DEFAULT 0 REFERENCES position_quality_epochs(epoch),
    PRIMARY KEY (epoch, minute, aircraft)
);
INSERT INTO position_quality_samples SELECT *, 0 FROM position_quality_samples_legacy;
DROP TABLE position_quality_samples_legacy;
CREATE INDEX position_quality_time ON position_quality_samples(observed);
ALTER TABLE position_quality_source ADD COLUMN epoch INTEGER NOT NULL DEFAULT 0;
