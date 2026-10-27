-- A small illustrative migration. Assess locks/production constraints manually.
ALTER TABLE projects ADD COLUMN IF NOT EXISTS notes text;
UPDATE projects SET notes = 'ready' WHERE id = 2;
CREATE INDEX CONCURRENTLY idx_projects_owner ON projects (owner_id);
-- DROP TABLE fake;
SELECT 'DROP TABLE not_real;';
