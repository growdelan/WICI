-- Preserve the exact bytes and hashes of every previously saved material.
DROP TRIGGER dossier_materials_immutable;
ALTER TABLE workspace_dossier_materials RENAME TO workspace_dossier_materials_v22;
CREATE TABLE workspace_dossier_materials (
 id TEXT PRIMARY KEY,
 dossier_id TEXT NOT NULL REFERENCES workspace_dossiers(id) ON DELETE CASCADE,
 title TEXT NOT NULL,
 kind TEXT NOT NULL CHECK(kind IN ('object','timeline','comparison','graph','event','infrastructure')),
 object_ref TEXT,
 captured_at TEXT NOT NULL,
 sha256 TEXT NOT NULL,
 byte_size INTEGER NOT NULL,
 snapshot_json TEXT NOT NULL
);
INSERT INTO workspace_dossier_materials SELECT * FROM workspace_dossier_materials_v22;
DROP TABLE workspace_dossier_materials_v22;
CREATE INDEX dossier_materials_parent ON workspace_dossier_materials(dossier_id,captured_at,id);
CREATE TRIGGER dossier_materials_immutable BEFORE UPDATE ON workspace_dossier_materials
BEGIN SELECT RAISE(ABORT,'Saved analysis material is immutable'); END;
