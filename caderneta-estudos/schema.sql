-- ============================================================
-- Caderneta de Estudos — schema Supabase/Postgres
-- Rode este arquivo inteiro no SQL Editor do seu projeto Supabase
-- (Project > SQL Editor > New query > cole tudo > Run).
-- ============================================================

create extension if not exists "uuid-ossp";

-- ---------------------------------------------------------------
-- profiles: um perfil por usuário autenticado (auth.users é gerido
-- automaticamente pelo Supabase Auth; esta tabela guarda os dados
-- extras do app).
-- ---------------------------------------------------------------
create table if not exists public.profiles (
  id uuid references auth.users on delete cascade primary key,
  full_name text,
  target_exam text default 'Banco do Brasil - Escriturário',
  city text default 'Goiânia',
  weekly_goal_hours numeric default 8,
  created_at timestamp with time zone default timezone('utc'::text, now()) not null
);

alter table public.profiles enable row level security;

create policy "profiles_select_own"
  on public.profiles for select
  using ( auth.uid() = id );

create policy "profiles_update_own"
  on public.profiles for update
  using ( auth.uid() = id );

create policy "profiles_insert_own"
  on public.profiles for insert
  with check ( auth.uid() = id );

-- cria o perfil automaticamente quando alguém se cadastra
create or replace function public.handle_new_user()
returns trigger as $$
begin
  insert into public.profiles (id, full_name)
  values (new.id, new.raw_user_meta_data->>'full_name');
  return new;
end;
$$ language plpgsql security definer;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute procedure public.handle_new_user();

-- ---------------------------------------------------------------
-- question_bank: banco de questões (do PRD, seção 5).
-- Leitura liberada para qualquer usuário autenticado.
-- Escrita feita só pelo script Python, usando a service_role key,
-- que ignora RLS por padrão — por isso não existe policy de INSERT
-- aqui para usuários comuns.
-- ---------------------------------------------------------------
create table if not exists public.question_bank (
  id uuid default uuid_generate_v4() primary key,
  discipline text not null,
  topic text not null,
  statement text not null,
  options jsonb not null,
  correct_answer text not null,
  explanation text,
  created_at timestamp with time zone default timezone('utc'::text, now()) not null
);

alter table public.question_bank enable row level security;

create policy "question_bank_select_authenticated"
  on public.question_bank for select
  using ( auth.role() = 'authenticated' );

create index if not exists question_bank_discipline_idx on public.question_bank (discipline);

-- ---------------------------------------------------------------
-- study_sessions: sessões de estudo registradas pelo usuário
-- (cronômetro / lançamento manual), usadas no gráfico "horas
-- estudadas" e nos cards de matéria do dashboard.
-- ---------------------------------------------------------------
create table if not exists public.study_sessions (
  id uuid default uuid_generate_v4() primary key,
  user_id uuid references auth.users on delete cascade not null,
  discipline text not null,
  minutes integer not null check (minutes > 0),
  session_date date not null default current_date,
  note text,
  created_at timestamp with time zone default timezone('utc'::text, now()) not null
);

alter table public.study_sessions enable row level security;

create policy "study_sessions_select_own"
  on public.study_sessions for select
  using ( auth.uid() = user_id );

create policy "study_sessions_insert_own"
  on public.study_sessions for insert
  with check ( auth.uid() = user_id );

create policy "study_sessions_delete_own"
  on public.study_sessions for delete
  using ( auth.uid() = user_id );

-- ---------------------------------------------------------------
-- quiz_attempts: resultado de cada simulado (por matéria ou
-- completo), usado no card "desempenho" e nos gráficos.
-- ---------------------------------------------------------------
create table if not exists public.quiz_attempts (
  id uuid default uuid_generate_v4() primary key,
  user_id uuid references auth.users on delete cascade not null,
  discipline text,
  attempt_type text not null default 'subject' check (attempt_type in ('subject', 'completo')),
  score numeric not null,
  total numeric not null,
  created_at timestamp with time zone default timezone('utc'::text, now()) not null
);

alter table public.quiz_attempts enable row level security;

create policy "quiz_attempts_select_own"
  on public.quiz_attempts for select
  using ( auth.uid() = user_id );

create policy "quiz_attempts_insert_own"
  on public.quiz_attempts for insert
  with check ( auth.uid() = user_id );

-- ============================================================
-- Fim do schema. Depois de rodar isto, vá em Project Settings >
-- API para pegar sua Project URL, a chave "anon public" (vai no
-- index.html) e a chave "service_role" (vai SÓ no GitHub Secrets,
-- nunca no front-end).
-- ============================================================
