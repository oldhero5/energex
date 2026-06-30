-- Observer RBAC + app metadata. Role is the source of truth in profiles and is injected into
-- the JWT by custom_access_token_hook so the observer-api can authorize from the verified token.

create type public.observer_role as enum ('viewer', 'operator', 'admin');

create table public.profiles (
  user_id uuid primary key references auth.users(id) on delete cascade,
  role public.observer_role not null default 'viewer',
  display_name text,
  created_at timestamptz not null default now()
);

create table public.audit_log (
  id bigint generated always as identity primary key,
  user_id uuid references auth.users(id),
  action text not null,
  target text,
  detail jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table public.saved_views (
  id bigint generated always as identity primary key,
  user_id uuid not null references auth.users(id) on delete cascade,
  name text not null,
  kind text not null,
  config jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table public.issue_acks (
  id bigint generated always as identity primary key,
  issue_key text not null,
  user_id uuid not null references auth.users(id),
  status text not null default 'open' check (status in ('open','ack','snoozed','resolved')),
  note text,
  created_at timestamptz not null default now()
);

-- helper: caller's role (security definer so RLS policies can call it)
create or replace function public.observer_current_role() returns public.observer_role
language sql stable security definer set search_path = public as $$
  select role from public.profiles where user_id = auth.uid()
$$;

alter table public.profiles enable row level security;
alter table public.audit_log enable row level security;
alter table public.saved_views enable row level security;
alter table public.issue_acks enable row level security;

-- profiles: any authenticated user may read; only admin may change a row (esp. role).
create policy profiles_read on public.profiles for select to authenticated using (true);
create policy profiles_admin_write on public.profiles for all to authenticated
  using (public.observer_current_role() = 'admin')
  with check (public.observer_current_role() = 'admin');

-- audit_log: admin reads; inserts come from the observer-api service role (never the client).
create policy audit_admin_read on public.audit_log for select to authenticated
  using (public.observer_current_role() = 'admin');

-- saved_views: a user manages only their own rows.
create policy saved_views_own on public.saved_views for all to authenticated
  using (user_id = auth.uid()) with check (user_id = auth.uid());

-- issue_acks: all authenticated read; operator/admin may insert their own.
create policy issue_acks_read on public.issue_acks for select to authenticated using (true);
create policy issue_acks_write on public.issue_acks for insert to authenticated
  with check (user_id = auth.uid() and public.observer_current_role() in ('operator','admin'));

-- new auth user -> default viewer profile
create or replace function public.handle_new_user() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  insert into public.profiles (user_id, display_name) values (new.id, new.email)
  on conflict (user_id) do nothing;
  return new;
end $$;

create trigger on_auth_user_created after insert on auth.users
  for each row execute function public.handle_new_user();

-- inject the role into the JWT as the top-level claim `user_role`
create or replace function public.custom_access_token_hook(event jsonb)
returns jsonb language plpgsql stable as $$
declare
  claims jsonb;
  resolved_role public.observer_role;
begin
  select role into resolved_role from public.profiles where user_id = (event->>'user_id')::uuid;
  claims := coalesce(event->'claims', '{}'::jsonb);
  claims := jsonb_set(claims, '{user_role}', to_jsonb(coalesce(resolved_role::text, 'viewer')));
  return jsonb_set(event, '{claims}', claims);
end $$;

-- the GoTrue auth admin role must be able to run the hook and read profiles
grant usage on schema public to supabase_auth_admin;
grant execute on function public.custom_access_token_hook to supabase_auth_admin;
grant select on table public.profiles to supabase_auth_admin;

-- RLS is enabled on profiles; the hook runs as supabase_auth_admin, which is not in the
-- `authenticated` role, so profiles_read does not apply to it. Without this policy the hook's
-- lookup returns no rows and every token silently falls back to 'viewer'. (Supabase RBAC pattern.)
create policy profiles_auth_admin_read on public.profiles
  for select to supabase_auth_admin using (true);
