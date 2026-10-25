-- Analyst work is independent of source retention and catalog projection rebuilds.
CREATE TABLE workspace_dossiers (
 id TEXT PRIMARY KEY,
 name TEXT NOT NULL,
 description TEXT NOT NULL DEFAULT '',
 revision INTEGER NOT NULL DEFAULT 1,
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL
);
CREATE TABLE workspace_dossier_pins (
 dossier_id TEXT NOT NULL REFERENCES workspace_dossiers(id) ON DELETE CASCADE,
 ref TEXT NOT NULL,
 label TEXT NOT NULL,
 type TEXT NOT NULL,
 source_id TEXT NOT NULL,
 pinned_at TEXT NOT NULL,
 PRIMARY KEY(dossier_id,ref)
);
CREATE TABLE workspace_dossier_notes (
 id TEXT PRIMARY KEY,
 dossier_id TEXT NOT NULL REFERENCES workspace_dossiers(id) ON DELETE CASCADE,
 body TEXT NOT NULL,
 revision INTEGER NOT NULL DEFAULT 1,
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL
);
CREATE INDEX dossier_notes_parent ON workspace_dossier_notes(dossier_id,created_at,id);
CREATE TABLE workspace_dossier_materials (
 id TEXT PRIMARY KEY,
 dossier_id TEXT NOT NULL REFERENCES workspace_dossiers(id) ON DELETE CASCADE,
 title TEXT NOT NULL,
 kind TEXT NOT NULL CHECK(kind IN ('object','timeline','comparison')),
 object_ref TEXT,
 captured_at TEXT NOT NULL,
 sha256 TEXT NOT NULL,
 byte_size INTEGER NOT NULL,
 snapshot_json TEXT NOT NULL
);
CREATE INDEX dossier_materials_parent ON workspace_dossier_materials(dossier_id,captured_at,id);
CREATE TRIGGER dossier_materials_immutable BEFORE UPDATE ON workspace_dossier_materials
BEGIN
 SELECT RAISE(ABORT,'Saved analysis material is immutable');
END;
