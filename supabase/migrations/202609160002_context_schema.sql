create table if not exists public.chunks (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  source_id uuid not null references public.sources(id) on delete cascade,
  owner_id uuid not null references auth.users(id) on delete cascade,
  position integer not null check (position >= 0),
  content text not null check (char_length(content) > 0),
  start_seconds double precision check (start_seconds is null or start_seconds >= 0),
  end_seconds double precision check (
    end_seconds is null or end_seconds >= coalesce(start_seconds, 0)
  ),
  embedding extensions.vector(1536),
  created_at timestamptz not null default now(),
  constraint uq_chunks_source_position unique (source_id, position)
);

create table if not exists public.contexts (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  source_id uuid not null references public.sources(id) on delete cascade,
  chunk_id uuid references public.chunks(id) on delete set null,
  owner_id uuid not null references auth.users(id) on delete cascade,
  kind varchar(40) not null check (
    kind in ('event', 'decision', 'task', 'fact', 'summary')
  ),
  title varchar(255) not null check (char_length(trim(title)) > 0),
  body text not null check (char_length(body) > 0),
  occurred_at timestamptz,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index if not exists chunks_workspace_id_idx on public.chunks(workspace_id);
create index if not exists chunks_source_id_idx on public.chunks(source_id);
create index if not exists chunks_owner_id_idx on public.chunks(owner_id);
create index if not exists chunks_embedding_hnsw_idx on public.chunks
  using hnsw (embedding extensions.vector_cosine_ops)
  where embedding is not null;
create index if not exists contexts_workspace_id_idx on public.contexts(workspace_id);
create index if not exists contexts_source_id_idx on public.contexts(source_id);
create index if not exists contexts_chunk_id_idx on public.contexts(chunk_id);
create index if not exists contexts_occurred_at_idx on public.contexts(occurred_at desc);

alter table public.chunks enable row level security;
alter table public.contexts enable row level security;

create policy "owners manage chunks" on public.chunks
  for all to authenticated
  using ((select auth.uid()) = owner_id)
  with check (
    (select auth.uid()) = owner_id
    and exists (
      select 1 from public.sources
      where sources.id = source_id
        and sources.workspace_id = workspace_id
        and sources.owner_id = (select auth.uid())
    )
  );

create policy "owners manage contexts" on public.contexts
  for all to authenticated
  using ((select auth.uid()) = owner_id)
  with check (
    (select auth.uid()) = owner_id
    and exists (
      select 1 from public.sources
      where sources.id = source_id
        and sources.workspace_id = workspace_id
        and sources.owner_id = (select auth.uid())
    )
    and (
      chunk_id is null
      or exists (
        select 1 from public.chunks
        where chunks.id = chunk_id
          and chunks.source_id = source_id
          and chunks.workspace_id = workspace_id
          and chunks.owner_id = (select auth.uid())
      )
    )
  );
