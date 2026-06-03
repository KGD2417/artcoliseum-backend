# Art Coliseum — FastAPI Backend

Replaces the deleted Supabase backend. PostgreSQL + JWT auth + local file uploads.

## Prerequisites
- Python 3.11+ (tested on 3.14)
- PostgreSQL — provided via Docker below

## 1. Start PostgreSQL (Docker)
```bash
docker run -d --name artcoliseum-pg \
  -e POSTGRES_USER=artcoliseum \
  -e POSTGRES_PASSWORD=artcoliseum \
  -e POSTGRES_DB=artcoliseum \
  -p 5433:5432 postgres:16
```
Already running? `docker start artcoliseum-pg`. Connection string lives in `.env`.

## 2. Install + run the API
```bash
cd artcoliseum-backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --reload --port 8000
```
Tables are auto-created on startup (dev). API docs: http://localhost:8000/docs

## 3. Run the frontend
```bash
cd ../artcoliseum-frontend
npm run dev   # Vite proxies /api and /uploads → :8000 (see vite.config.js)
```
Register/sign in at `/signin` — accounts are active immediately (no email confirmation).

## Make yourself an admin
Register normally, then promote the account once:
```bash
docker exec artcoliseum-pg psql -U artcoliseum -d artcoliseum \
  -c "UPDATE profiles SET role='admin', is_admin=true WHERE user_id=(SELECT id FROM users WHERE email='YOU@EMAIL.com');"
```

## Phase status
- **Phase 1 (done):** JWT auth (register/login/refresh/logout/me), file uploads, static serving.
- Phases 2–6: catalog, chat, enquiry→buy→delivery→review, artist/competition, community/admin.

## Endpoints (Phase 1)
| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| POST | /auth/register | – | create account, returns tokens |
| POST | /auth/login | – | returns access + refresh tokens |
| POST | /auth/refresh | – | new tokens from a refresh token |
| POST | /auth/logout | bearer | (stateless; client discards tokens) |
| GET  | /auth/me | bearer | current user, role, artist_status |
| POST | /uploads | bearer | multipart {file, kind=image\|video\|model} → {url} |
| GET  | /uploads/... | – | static file serving |
| GET  | /health | – | health check |
