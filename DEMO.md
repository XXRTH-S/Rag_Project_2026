# Closed interview demo

Five synthetic accounts: demo01@example.com through demo05@example.com. Credentials are in the root `.env` under `DEMO_USER_1_EMAIL` / `DEMO_USER_1_PASSWORD` through 5. Do not share `.env`, include it in recordings, or upload it to Vercel. The database stores bcrypt hashes only. Existing admin accounts and documents are preserved.

## Provision / repeat safely

```powershell
.\dc.ps1 run --rm --no-deps -T api python scripts/seed_demo.py --fixtures
```

This is an explicit command, not startup synchronization. Reruns leave passwords, suspension status, and existing fixtures unchanged. Account collisions fail before creating any accounts. Fixtures are synthetic and use the separate `demo-fixtures-v1` collection; each user sees their own file. Initial fixtures do not consume daily upload quota. Each account has the normal 5-document / 500-page daily quota.

## Data expiry

```powershell
.\dc.ps1 run --rm --no-deps -T api python scripts/retention_demo.py
.\dc.ps1 --profile demo up -d demo-retention
```

The first command previews changes. The optional demo service applies cleanup every hour, deleting demo-owned data older than 90 days. It skips documents with unfinished ingestion jobs. It removes original files, document rows/chunks, answers citing expired documents, old demo chat messages and old usage records. It does not delete accounts or data owned by existing non-demo users. It does not delete historical backup archives; keep demo databases out of persistent backups, or expire those archives separately. No backup deletion is performed automatically.

## Vercel

Target project: `prj_4cqCBJjVFg9I7EAW0qr2otkUy1HJ`.

`vercel-deploy.ps1` sets `VERCEL_PROJECT_ID` and invokes the CLI from `web` (`--cwd web`), using `web/vercel.json`. This records the requested deployment target locally; it does not change remote project settings or publish automatically. Backend and GPU services remain in Docker. A public HTTPS backend URL and the matching CORS/cookie configuration are still needed for a hosted frontend. Do not set credentials as NEXT_PUBLIC variables.

## Verification

API regression tests use a separate test database. Browser script `scripts/demo-browser-check.cjs` reads secrets without logging them and tests five logins, documents, quota, admin denial, cross-account denial, and a real chat. Set PLAYWRIGHT_MODULE to your installed Playwright module path. Browser artifacts go to ignored `output/playwright/`.

## HTTPS demo connection

The Vercel frontend proxies `/api/*` and `/health/*` to `BACKEND_HTTPS_ORIGIN` (production environment variable). The ngrok token stays only in the root `.env`; it is not uploaded to Vercel. Browser API calls send `ngrok-skip-browser-warning` so ngrok returns API responses instead of its interstitial page.

Start the HTTPS demo with:

```powershell
docker compose -f docker-compose.yml -f docker-compose.local.yml -f docker-compose.override.yml -f docker-compose.https.yml up -d ngrok
```

Keep this computer, Docker and ngrok running while presenting. The HTTPS override enables Secure cookies and disables trusting caller-supplied forwarding headers. Login throttling is conservatively shared at the proxy connection in this mode.

The current tunnel URL was assigned automatically. After restarting ngrok, verify its URL; if it changes, update Vercel's production `BACKEND_HTTPS_ORIGIN` and redeploy with `vercel-deploy.ps1 --prod --yes`. Use a reserved ngrok domain for a stable URL. Root `.env` must never be uploaded.