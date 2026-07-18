-- 라디오 데스크 — Supabase 스키마 (SQL Editor에서 실행)
-- Google 로그인 사용자 프로필 + 일일 번역 쿼터

create table if not exists public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  email text,
  plan text not null default 'free',
  created_at timestamptz not null default now()
);

create table if not exists public.translate_usage (
  user_id uuid not null references auth.users(id) on delete cascade,
  usage_date date not null,
  used_count int not null default 0 check (used_count >= 0),
  primary key (user_id, usage_date)
);

alter table public.profiles enable row level security;
alter table public.translate_usage enable row level security;

drop policy if exists "profiles_select_own" on public.profiles;
create policy "profiles_select_own"
  on public.profiles for select
  using (auth.uid() = id);

drop policy if exists "profiles_insert_own" on public.profiles;
create policy "profiles_insert_own"
  on public.profiles for insert
  with check (auth.uid() = id);

drop policy if exists "profiles_update_own" on public.profiles;
create policy "profiles_update_own"
  on public.profiles for update
  using (auth.uid() = id);

drop policy if exists "usage_select_own" on public.translate_usage;
create policy "usage_select_own"
  on public.translate_usage for select
  using (auth.uid() = user_id);

drop policy if exists "usage_insert_own" on public.translate_usage;
create policy "usage_insert_own"
  on public.translate_usage for insert
  with check (auth.uid() = user_id);

drop policy if exists "usage_update_own" on public.translate_usage;
create policy "usage_update_own"
  on public.translate_usage for update
  using (auth.uid() = user_id);

-- 신규 유저 자동 프로필
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  insert into public.profiles (id, email, plan)
  values (new.id, new.email, 'free')
  on conflict (id) do update set email = excluded.email;
  return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();

-- 일일 쿼터 차감 (KST 날짜). 반환: 차감 후 잔여
create or replace function public.consume_translate_quota(p_n int, p_limit int)
returns int
language plpgsql
security definer
set search_path = public
as $$
declare
  v_uid uuid := auth.uid();
  v_date date := (timezone('Asia/Seoul', now()))::date;
  v_used int;
begin
  if v_uid is null then
    raise exception 'not authenticated';
  end if;
  if p_n is null or p_n <= 0 then
    select coalesce(used_count, 0) into v_used
    from public.translate_usage
    where user_id = v_uid and usage_date = v_date;
    return greatest(0, p_limit - coalesce(v_used, 0));
  end if;

  insert into public.translate_usage (user_id, usage_date, used_count)
  values (v_uid, v_date, least(p_n, p_limit))
  on conflict (user_id, usage_date)
  do update set used_count = least(
    public.translate_usage.used_count + excluded.used_count,
    p_limit
  )
  returning used_count into v_used;

  return greatest(0, p_limit - v_used);
end;
$$;

grant execute on function public.consume_translate_quota(int, int) to authenticated;
