-- Lock down the Growmated Engine database (project rkhcbvssmfxoajqvsqma).
--
-- ⚠️ RUN THIS ONLY AFTER the app is using the SERVICE ROLE key.
--
-- Why: every table currently has RLS disabled, so anyone holding the publishable key can
-- read and modify all 134 prospects, 9 clients, and the income/expenses tables. The
-- publishable key is designed to be shared with browsers, so it must be treated as public.
--
-- The design: enable RLS with NO policies. That denies the `anon` and `authenticated`
-- roles completely. The `service_role` key bypasses RLS by design, and Streamlit runs
-- Python server-side, so that key never reaches a browser. Result: the app keeps working,
-- and a leaked publishable key grants nothing.
--
-- ORDER OF OPERATIONS (do not skip step 2):
--   1. Supabase dashboard -> Project Settings -> API -> copy the `service_role` key
--   2. Set SUPABASE_KEY to that value in .env AND in the deployed app's secrets
--   3. Restart the app and confirm the pipeline still loads
--   4. Run this file
--
-- Rollback if something breaks:
--   alter table public.<name> disable row level security;

alter table public.pipeline          enable row level security;
alter table public.outreach_log      enable row level security;
alter table public.content_calendar  enable row level security;
alter table public.clients           enable row level security;
alter table public.income            enable row level security;
alter table public.expenses          enable row level security;
alter table public.time_logs         enable row level security;
alter table public.goals             enable row level security;
alter table public.facebook_posts    enable row level security;
alter table public.templates         enable row level security;
alter table public.activity_log      enable row level security;

-- Verify: rowsecurity should be true for all 11 tables.
select tablename, rowsecurity
from pg_tables
where schemaname = 'public'
order by tablename;
