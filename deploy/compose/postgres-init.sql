-- Local development only. Production roles/databases come from OpenTofu + migrations.
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS ltree;
-- Application role: not the table owner, so FORCE ROW LEVEL SECURITY applies to it.
CREATE ROLE nexiqon_app LOGIN PASSWORD 'nexiqon_app_dev';
GRANT CONNECT ON DATABASE nexiqon TO nexiqon_app;
