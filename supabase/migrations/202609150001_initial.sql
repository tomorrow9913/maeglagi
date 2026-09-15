create extension if not exists pgcrypto;

create table if not exists public.workspaces (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users(id) on delete cascade,
  name varchar(120) not null check (char_length(trim(name)) > 0),
  created_at timestamptz not null default now()
);

create table if not exists public.sources (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  owner_id uuid not null references auth.users(id) on delete cascade,
  kind varchar(20) not null check (kind in ('document', 'meeting')),
  title varchar(255) not null,
  object_path text not null unique,
  content_type varchar(120) not null,
  size_bytes bigint not null check (size_bytes >= 0),
  status varchar(20) not null default 'queued',
  created_at timestamptz not null default now()
);

create index if not exists workspaces_owner_id_idx on public.workspaces(owner_id);
create index if not exists sources_workspace_id_idx on public.sources(workspace_id);
create index if not exists sources_owner_id_idx on public.sources(owner_id);

alter table public.workspaces enable row level security;
alter table public.sources enable row level security;

create policy "owners manage workspaces" on public.workspaces
  for all to authenticated
  using ((select auth.uid()) = owner_id)
  with check ((select auth.uid()) = owner_id);

create policy "owners manage sources" on public.sources
  for all to authenticated
  using ((select auth.uid()) = owner_id)
  with check (
    (select auth.uid()) = owner_id
    and exists (
      select 1 from public.workspaces
      where workspaces.id = workspace_id and workspaces.owner_id = (select auth.uid())
    )
  );

insert into storage.buckets (id, name, public)
values ('sources', 'sources', false)
on conflict (id) do update set public = false;

create policy "users upload own sources" on storage.objects
  for insert to authenticated
  with check (bucket_id = 'sources' and (storage.foldername(name))[1] = (select auth.uid())::text);

create policy "users read own sources" on storage.objects
  for select to authenticated
  using (bucket_id = 'sources' and owner_id = (select auth.uid())::text);

create policy "users delete own sources" on storage.objects
  for delete to authenticated
  using (bucket_id = 'sources' and owner_id = (select auth.uid())::text);
