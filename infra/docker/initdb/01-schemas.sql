-- Extensions and schemas. Runs once on first container start.

CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS postgis_topology;
CREATE EXTENSION IF NOT EXISTS pg_trgm;      -- fuzzy locality search
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE SCHEMA IF NOT EXISTS raw;        -- immutable landing zone, as-fetched
CREATE SCHEMA IF NOT EXISTS ref;        -- authoritative reference data
CREATE SCHEMA IF NOT EXISTS osm;        -- OpenStreetMap-derived features
CREATE SCHEMA IF NOT EXISTS market;     -- listings, guidance values, history
CREATE SCHEMA IF NOT EXISTS user_data;  -- accounts, study subjects, documents
CREATE SCHEMA IF NOT EXISTS analytics;  -- materialised aggregates
CREATE SCHEMA IF NOT EXISTS ml;         -- features, predictions, explanations
CREATE SCHEMA IF NOT EXISTS meta;       -- provenance, sources, audit

COMMENT ON SCHEMA raw IS
  'As-fetched payloads. Never edited, never served. Re-derivable truth.';
COMMENT ON SCHEMA meta IS
  'Provenance and audit. Every user-facing value traces back to a row here.';
COMMENT ON SCHEMA user_data IS
  'Restricted. Contains uploaded documents and any owner details they carry. '
  'Never joined into analytics, ml or tile queries.';
