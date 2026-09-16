-- Supabase is the single operational storage platform for the PoC.
-- Relational metadata, vectors, and graph projections share PostgreSQL;
-- immutable source files live in the private Storage bucket.
create extension if not exists vector with schema extensions;

insert into storage.buckets (id, name, public)
values ('sources', 'sources', false)
on conflict (id) do update set public = false;
