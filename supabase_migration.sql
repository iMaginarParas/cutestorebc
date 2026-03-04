-- ============================================================
-- Run this in your Supabase SQL Editor
-- ============================================================

-- 1. Purchases table
create table if not exists public.purchases (
  id                   uuid primary key default gen_random_uuid(),
  user_id              uuid not null references auth.users(id) on delete cascade,
  razorpay_order_id    text unique not null,
  razorpay_payment_id  text,
  razorpay_signature   text,
  amount_paise         integer not null,
  currency             text not null default 'INR',
  status               text not null default 'pending',  -- pending | paid | failed
  created_at           timestamptz not null default now(),
  paid_at              timestamptz
);

-- 2. Product access table
create table if not exists public.product_access (
  user_id              uuid primary key references auth.users(id) on delete cascade,
  razorpay_order_id    text,
  granted_at           timestamptz not null default now()
);

-- 3. RLS – only owners can read their own rows
alter table public.purchases enable row level security;
alter table public.product_access enable row level security;

create policy "Users can view own purchases"
  on public.purchases for select
  using (auth.uid() = user_id);

create policy "Users can view own access"
  on public.product_access for select
  using (auth.uid() = user_id);

-- 4. Service role can do everything (used by the FastAPI backend)
-- (Service role bypasses RLS by default — no extra policy needed)

-- 5. Enable Google OAuth in Supabase Dashboard:
--    Authentication → Providers → Google → Enable
--    Set Client ID + Secret from Google Cloud Console
--    Redirect URL: https://your-project.supabase.co/auth/v1/callback
