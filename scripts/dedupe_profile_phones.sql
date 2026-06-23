-- Resolve duplicate phone numbers so the uq_profiles_phone unique index can apply.
--
-- Policy: for each shared phone number, the NEWEST account (latest created_at)
-- keeps it; every older duplicate has its phone cleared to NULL. No accounts,
-- orders, or artworks are deleted — only the phone field on the losing rows is
-- cleared, so those users can re-add a (now-unique) number later.
--
-- Blank / whitespace-only phones are also normalised to NULL, matching how the
-- app now stores "no phone".
--
-- How to run (DB must be reachable; uses the same DATABASE_URL as the app):
--   psql "$DATABASE_URL" -f scripts/dedupe_profile_phones.sql
-- Run the PREVIEW section first, eyeball it, then run the APPLY transaction.

-- ── Preview: blank phones that will be normalised to NULL (read-only) ─────────
SELECT u.email, p.role, p.created_at, p.phone
FROM profiles p
JOIN users u ON u.id = p.user_id
WHERE p.phone IS NOT NULL AND btrim(p.phone) = ''
ORDER BY p.created_at;

-- ── Preview: colliding groups, marking which account keeps the number ─────────
WITH dupes AS (
    SELECT p.phone,
           p.created_at,
           u.email,
           p.role,
           row_number() OVER (PARTITION BY p.phone
                              ORDER BY p.created_at DESC, p.user_id DESC) AS rn,
           count(*)     OVER (PARTITION BY p.phone)                      AS group_size
    FROM profiles p
    JOIN users u ON u.id = p.user_id
    WHERE p.phone IS NOT NULL AND btrim(p.phone) <> ''
)
SELECT phone,
       email,
       role,
       created_at,
       CASE WHEN rn = 1 THEN 'KEEP (newest)' ELSE 'CLEAR' END AS action
FROM dupes
WHERE group_size > 1
ORDER BY phone, rn;

-- ── Apply ────────────────────────────────────────────────────────────────────
BEGIN;

-- 1) Blank / whitespace-only phones → NULL.
UPDATE profiles
SET phone = NULL
WHERE phone IS NOT NULL AND btrim(phone) = '';

-- 2) For each real phone, clear it from every account except the newest.
WITH ranked AS (
    SELECT id,
           row_number() OVER (PARTITION BY phone
                              ORDER BY created_at DESC, user_id DESC) AS rn
    FROM profiles
    WHERE phone IS NOT NULL AND btrim(phone) <> ''
)
UPDATE profiles p
SET phone = NULL
FROM ranked r
WHERE p.id = r.id AND r.rn > 1;

COMMIT;

-- ── Verify (read-only) — should return zero rows after the apply ─────────────
SELECT phone, count(*)
FROM profiles
WHERE phone IS NOT NULL AND btrim(phone) <> ''
GROUP BY phone
HAVING count(*) > 1;
