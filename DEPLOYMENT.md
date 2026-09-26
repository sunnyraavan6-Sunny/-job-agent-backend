# Deploying to Railway

Three services in one Railway project: the MySQL database, the backend API,
and the frontend. Roughly 20 minutes end to end.

## 0. Prerequisites

- A Railway account (railway.app)
- These two project folders pushed to a GitHub repo each (or two repos) --
  Railway deploys from a Git repo or via `railway up` from the CLI. Either
  works; these steps assume GitHub since it's the simpler path for updates.

## 1. Create the project and the database

1. New Project → **Deploy MySQL** (from the database templates). This
   provisions a `MySQL` service with a persistent volume already attached.
2. Note the service name shown on the canvas -- it defaults to `MySQL`.
   Reference variables below assume that name; adjust if you renamed it.

## 2. Deploy the backend

1. In the same project: **New → GitHub Repo** → select the `job_agent`
   repo (the one containing `Dockerfile` and `railway.json` at its root).
   Railway reads `railway.json` and builds from the Dockerfile automatically
   -- no manual build config needed.
2. Once it's created, open the service → **Variables**, and add:

   ```
   MYSQL_HOST=${{MySQL.MYSQLHOST}}
   MYSQL_PORT=${{MySQL.MYSQLPORT}}
   MYSQL_USER=${{MySQL.MYSQLUSER}}
   MYSQL_PASSWORD=${{MySQL.MYSQLPASSWORD}}
   MYSQL_DATABASE=${{MySQL.MYSQLDATABASE}}
   SECRET_KEY=<generate a long random string -- e.g. `openssl rand -hex 32`>
   ACCESS_TOKEN_EXPIRE_MINUTES=1440
   ENVIRONMENT=production
   ```

   These `${{Service.VAR}}` references pull live values from the MySQL
   service -- you never copy/paste the actual password.

3. Optional, add only what you're using:
   ```
   ADZUNA_APP_ID=...
   ADZUNA_APP_KEY=...
   SMTP_HOST=...
   SMTP_USERNAME=...
   SMTP_PASSWORD=...
   SMTP_FROM_EMAIL=...
   ANTHROPIC_API_KEY=...
   ```
4. **Settings → Networking → Generate Domain** to get a public URL
   (something like `job-agent-api-production.up.railway.app`). The
   Dockerfile already reads Railway's injected `$PORT`, so no port config
   needed.
5. **Add a Volume**: Settings → Volumes → New Volume, mount path
   `/code/generated_resumes`. Without this, tailored resume PDFs disappear
   on every redeploy.
6. Deploy. Check `https://<your-backend-domain>/health` returns `{"status": "ok"}`
   and `/docs` loads the Swagger UI.

## 3. Deploy the frontend

1. **New → GitHub Repo** → select the `job_agent_frontend` repo.
2. Open the service → **Variables**, add as a variable (Railway passes
   service variables as Docker build args automatically, which is what the
   frontend's `ARG VITE_API_BASE_URL` picks up):
   ```
   VITE_API_BASE_URL=https://<your-backend-domain>
   ```
   Use the actual backend domain from step 2.4, including `https://`.
3. **Settings → Networking → Generate Domain**.
4. Deploy. Open the generated URL -- you should see the login page.

## 4. Lock down CORS

Right now the backend's `CORS_ORIGINS` defaults to `*` (fine for getting
things working). Once the frontend has its real domain:

1. Back on the **backend** service → Variables, add:
   ```
   CORS_ORIGINS=https://<your-frontend-domain>
   ```
2. Redeploy the backend. It'll now only accept browser requests from your
   actual frontend, not from anywhere on the internet.

## 5. First login

Open the frontend URL, register an account, and work through the sidebar in
order (master resume → jobs → applications → outreach → learning), same as
the local walkthrough in each project's README.

## Before this becomes your daily driver

- **Migrations**: the backend currently creates tables via
  `Base.metadata.create_all` on startup. That's fine for the first deploy,
  but any schema change after that (a new column, say) won't be applied
  automatically. Switch to Alembic migrations before making schema changes
  against real data you care about (see the note in `job_agent/README.md`).
- **Backups**: Railway's MySQL template doesn't back up automatically by
  default -- add their native Backups feature (Settings on the MySQL
  service) once there's real data here.
- **Secrets**: everything above went through Railway's Variables UI, not
  into a committed `.env` -- keep it that way; don't commit real credentials
  to the repo even though `.env.example` ships with placeholders.
- **Cost**: this is a single-tenant personal tool, not a high-traffic
  service -- Railway's Hobby plan usage-based pricing should stay cheap
  (the services idle when you're not using them). Check current pricing at
  railway.com/pricing since this changes.
