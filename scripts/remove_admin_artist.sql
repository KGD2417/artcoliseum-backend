-- Remove the "artist" identity that coincides with an admin account.
--
-- Why this is needed: an admin who was also onboarded as an artist ends up with
-- a catalog `artists` row + `artist_kyc` row + an "artist" profile status, so the
-- admin shows up in the public Artists listing and sees the Artist Studio.
--
-- The catalog artist id is derived from the user id the same way the app does it
-- (app/routers/admin.py::_artist_slug):  'artist-' || first 8 hex chars of the UUID.
--
-- 1) Edit the email below to the admin account you want to clean up.
-- 2) Run the SELECT first to confirm it targets the right user / artist row.
-- 3) Run the transaction to apply.

\set admin_email '''kshitijdesai179@gmail.com'''

-- ── Preview (safe, read-only) ────────────────────────────────────────────────
SELECT u.id AS user_id,
       u.email,
       p.role,
       p.artist_status,
       'artist-' || substr(replace(u.id::text, '-', ''), 1, 8) AS artist_slug,
       (SELECT count(*) FROM artworks aw
          WHERE aw.artist_id = 'artist-' || substr(replace(u.id::text, '-', ''), 1, 8)) AS artworks_attributed
FROM users u
JOIN profiles p ON p.user_id = u.id
WHERE u.email = :admin_email;

-- ── Apply ────────────────────────────────────────────────────────────────────
BEGIN;

-- Detach any artworks attributed to the admin's artist slug (kept, just unlinked).
UPDATE artworks
SET artist_id = NULL
WHERE artist_id = 'artist-' || substr(replace(
        (SELECT id FROM users WHERE email = :admin_email)::text, '-', ''), 1, 8);

-- Remove the catalog artist profile → drops them from the Artists listing.
DELETE FROM artists
WHERE id = 'artist-' || substr(replace(
        (SELECT id FROM users WHERE email = :admin_email)::text, '-', ''), 1, 8);

-- Remove the artist KYC / application record → drops them from the admin Artists tab.
DELETE FROM artist_kyc
WHERE user_id = (SELECT id FROM users WHERE email = :admin_email);

-- Reset the profile so they are a pure admin again (not an artist).
UPDATE profiles
SET role = 'admin', artist_status = 'none'
WHERE user_id = (SELECT id FROM users WHERE email = :admin_email);

COMMIT;
