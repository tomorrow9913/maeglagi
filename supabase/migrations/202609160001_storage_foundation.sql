-- Supabase is the single operational storage platform for the PoC.
-- Relational metadata and vectors share PostgreSQL; immutable source files
-- live in the private Storage bucket. Graph data is stored in Neo4j.
create extension if not exists vector with schema extensions;

insert into storage.buckets (id, name, public)
values ('sources', 'sources', false)
on conflict (id) do update set public = false;
