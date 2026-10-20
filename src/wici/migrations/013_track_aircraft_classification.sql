ALTER TABLE object_tracks ADD COLUMN military INTEGER CHECK (military IN (0, 1));
