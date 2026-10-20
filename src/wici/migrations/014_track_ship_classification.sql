ALTER TABLE object_tracks ADD COLUMN ship_type_code INTEGER
    CHECK (ship_type_code IS NULL OR (typeof(ship_type_code) = 'integer' AND ship_type_code BETWEEN 1 AND 99));
