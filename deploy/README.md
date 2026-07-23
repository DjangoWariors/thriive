# Thriive IMS — EC2 Deployment

Bare-metal deploy on a single Ubuntu 24.04 EC2 instance (one instance per client —
no Docker). Stack: **Nginx → Gunicorn → Django**, **PostgreSQL 17**, **Redis**,
**Celery** (worker + beat), all supervised by **Supervisor**. The app lives in
`/var/www/html/thriive`.

```
Browser ──▶ Nginx :80/:443
             ├── /            → React SPA  (frontend/dist)
             ├── /api, /admin → Gunicorn 127.0.0.1:8000  (Django)
             ├── /static      → backend/staticfiles
             └── /media       → backend/media
Supervisor ──▶ gunicorn · celery worker · celery beat
Redis ─── broker + cache        PostgreSQL 17 ─── data
```

## Files

| File | Purpose |
|------|---------|
| `setup.sh` | One-shot bootstrap of a fresh box (packages, PG 17, Redis, DB, Nginx, Supervisor). Run once as root. |
| `deploy.sh` | Redeploy on code changes (deps, migrate, build, restart). Run as the `thriive` user. |
| `nginx/thriive.conf` | Nginx site (SPA + reverse proxy). `__DOMAIN__`/`__APP_DIR__` filled in by `setup.sh`. |
| `supervisor/thriive.conf` | Gunicorn + Celery worker + beat process group. |
| `env.prod.example` | Production `.env` template → copied to `backend/.env`. |

## First deploy

1. **Provision** an Ubuntu 24.04 EC2 instance. Open ports **22, 80, 443** in the
   security group.

2. **Place the code** at `/var/www/html/thriive`:

   ```bash
   sudo mkdir -p /var/www/html
   sudo git clone <repo-url> /var/www/html/thriive
   # or: rsync -az ./ ec2:/var/www/html/thriive
   ```

3. **Run setup.** Two modes:

   **A) Demo on a bare IP (no domain, plain HTTP)** — pass your instance's public
   IP (or leave it out to auto-detect):

   ```bash
   sudo SERVER_IP=13.234.56.78 DB_PASSWORD='<strong-password>' \
        bash /var/www/html/thriive/deploy/setup.sh
   ```

   Then browse to `http://13.234.56.78/`. (Make sure port **80** is open in the
   security group.) `SERVER_IP`, `HOST`, and `DOMAIN` are interchangeable; omit
   all three and the script auto-detects the EC2 public IP.

   **B) Real domain with HTTPS:**

   ```bash
   sudo DOMAIN=thriive.acme.com ENABLE_HTTPS=true DB_PASSWORD='<strong-password>' \
        bash /var/www/html/thriive/deploy/setup.sh
   ```

   Either mode installs everything, creates the `thriive` DB + role, generates
   `backend/.env` (with a random `SECRET_KEY`), builds the frontend, migrates,
   seeds RBAC roles, and starts all processes.

4. **Create an admin user:**

   ```bash
   sudo -u thriive /var/www/html/thriive/backend/venv/bin/python \
        /var/www/html/thriive/backend/manage.py createsuperuser
   ```

5. **Enable HTTPS** once you have a domain (skip for the IP demo):

   ```bash
   sudo DOMAIN=thriive.acme.com ENABLE_HTTPS=true bash deploy/setup.sh
   sudo certbot --nginx -d thriive.acme.com
   ```

## Updating (redeploys)

```bash
cd /var/www/html/thriive && sudo -u thriive git pull
sudo -u thriive bash deploy/deploy.sh
```

`deploy.sh` reinstalls Python deps, runs migrations, rebuilds the SPA, collects
static, and `supervisorctl restart thriive:`. The sudo grant this needs is
installed by `setup.sh` (`/etc/sudoers.d/thriive`):

```
thriive ALL=(root) NOPASSWD: /usr/bin/supervisorctl restart thriive\:, /usr/bin/supervisorctl status thriive\:
```

(Exact commands, no wildcards — recent sudo rejects wildcards in command
arguments; the `:` must be backslash-escaped in sudoers.)

## HTTP demo vs. HTTPS

`config/settings/prod.py` reads the HTTPS-enforcement flags from the environment
(`SECURE_SSL_REDIRECT`, `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`), all
defaulting to **secure**. `setup.sh` writes them into `backend/.env` based on the
mode:

| Mode | `.env` values | Behaviour |
|------|---------------|-----------|
| IP demo (`ENABLE_HTTPS=false`, the default when no `DOMAIN`) | `False` | App serves over plain HTTP on the IP; no redirect loop, admin login works. |
| Domain (`ENABLE_HTTPS=true`) | `True` | Django 301-redirects HTTP→HTTPS, secure cookies, HSTS. Run `certbot`. |

**Going from demo to production:** point a domain at the box, then
`sudo DOMAIN=your.domain ENABLE_HTTPS=true bash deploy/setup.sh` and
`certbot --nginx -d your.domain`. Re-running setup with an explicit
`DOMAIN`/`SERVER_IP` updates the host + TLS keys in the existing `.env`
(`ALLOWED_HOSTS`, the three `SECURE_*`/`*_COOKIE_SECURE` flags,
`CSRF_TRUSTED_ORIGINS`, `CORS_ALLOWED_ORIGINS`); everything else is preserved.
A re-run *without* a host leaves `.env` untouched. Never leave the flags `False`
once TLS is in front of the app. `prod.py` already sets
`SECURE_PROXY_SSL_HEADER` so Django trusts Nginx's `X-Forwarded-Proto`.

## Operations cheat-sheet

```bash
sudo supervisorctl status thriive:           # process health
sudo supervisorctl restart thriive:web       # just gunicorn
sudo supervisorctl restart thriive:          # everything

tail -f /var/log/thriive/web.log             # gunicorn
tail -f /var/log/thriive/celery-compute.log  # celery worker: payouts + achievements
tail -f /var/log/thriive/celery-io.log       # celery worker: default + reports
tail -f /var/log/thriive/beat.log            # celery beat
tail -f /var/log/thriive/django.log          # app logs (RotatingFileHandler, prod.py)

sudo systemctl status nginx postgresql redis-server
ls /var/backups/thriive/                     # nightly pg_dump (14-day retention)
```

## Notes

- **Celery is not optional.** Achievement runs, payout computation, target
  disaggregation, report generation and bulk imports are Celery tasks — the
  workers + beat processes must stay up. Two workers: `celery_compute`
  (payouts, achievements) and `celery_io` (default, reports), so month-close
  compute never queues behind report generation.
- **Sizing:** Gunicorn runs `2*nproc+1` gthread workers (x4 threads, capped
  at 24 — override with `GUNICORN_WORKERS=` when re-running setup). `setup.sh`
  writes a PostgreSQL tuning drop-in scaled to instance RAM
  (`/etc/postgresql/*/main/conf.d/thriive.conf`); re-run setup after resizing
  the instance to regenerate both.
- **Backups:** nightly `pg_dump` to `/var/backups/thriive/` (cron, 01:30,
  14-day retention). Local-only — ship them off-box (S3) for real DR.
- **Log dir** `/var/log/thriive` is created by `setup.sh`; `prod.py` writes
  `django.log` there.
- **Per-client isolation:** one DB, one Redis, one EC2 per client. No shared
  schemas — repeat this whole process per client instance.
