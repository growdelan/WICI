-- Keep existing immutable JSON bytes and hashes unchanged while adding graph material.
DROP TRIGGER dossier_materials_immutable;
ALTER TABLE workspace_dossier_materials RENAME TO workspace_dossier_materials_v19;
CREATE TABLE workspace_dossier_materials (
 id TEXT PRIMARY KEY,
 dossier_id TEXT NOT NULL REFERENCES workspace_dossiers(id) ON DELETE CASCADE,
 title TEXT NOT NULL,
 kind TEXT NOT NULL CHECK(kind IN ('object','timeline','comparison','graph')),
 object_ref TEXT,
 captured_at TEXT NOT NULL,
 sha256 TEXT NOT NULL,
 byte_size INTEGER NOT NULL,
 snapshot_json TEXT NOT NULL
);
INSERT INTO workspace_dossier_materials SELECT * FROM workspace_dossier_materials_v19;
DROP TABLE workspace_dossier_materials_v19;
CREATE INDEX dossier_materials_parent ON workspace_dossier_materials(dossier_id,captured_at,id);
CREATE TRIGGER dossier_materials_immutable BEFORE UPDATE ON workspace_dossier_materials
BEGIN
 SELECT RAISE(ABORT,'Saved analysis material is immutable');
END;
CREATE TABLE workspace_relations (
 id TEXT PRIMARY KEY,
 dossier_id TEXT NOT NULL REFERENCES workspace_dossiers(id) ON DELETE CASCADE,
 source_ref TEXT NOT NULL,
 target_ref TEXT NOT NULL,
 source_label TEXT NOT NULL,
 target_label TEXT NOT NULL,
 source_type TEXT NOT NULL,
 target_type TEXT NOT NULL,
 justification TEXT NOT NULL,
 note_id TEXT,
 material_id TEXT,
 revision INTEGER NOT NULL DEFAULT 1,
 deleted INTEGER NOT NULL DEFAULT 0 CHECK(deleted IN (0,1)),
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 CHECK(source_ref<target_ref)
);
CREATE UNIQUE INDEX relation_active_pair ON workspace_relations(dossier_id,source_ref,target_ref) WHERE deleted=0;
CREATE INDEX relation_source ON workspace_relations(dossier_id,source_ref,deleted);
CREATE INDEX relation_target ON workspace_relations(dossier_id,target_ref,deleted);
CREATE TABLE workspace_relation_revisions (
 relation_id TEXT NOT NULL REFERENCES workspace_relations(id) ON DELETE CASCADE,
 revision INTEGER NOT NULL,
 action TEXT NOT NULL CHECK(action IN ('create','update','delete')),
 payload_json TEXT NOT NULL,
 at TEXT NOT NULL,
 PRIMARY KEY(relation_id,revision)
);
CREATE TABLE workspace_graphs (
 dossier_id TEXT PRIMARY KEY REFERENCES workspace_dossiers(id) ON DELETE CASCADE,
 config_json TEXT NOT NULL,
 revision INTEGER NOT NULL,
 updated_at TEXT NOT NULL
);
