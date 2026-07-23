#!/usr/bin/env bash
#
# Thriive IMS — one-shot EC2 bootstrap.
# Run ONCE as root on a fresh Ubuntu instance (24.04 LTS or newer; tested against
# 25.10 / Python 3.13), after the repo is placed at /var/www/html/thriive
# (git clone or rsync). Idempotent enough to re-run safely.
#
#   sudo bash /var/www/html/thriive/deploy/setup.sh
#
# For subsequent code updates use deploy.sh instead — this script installs the
# whole box (system packages, Postgres 17, Redis, Nginx, Supervisor).
set -euo pipefail

# --- Tunables (override via env before running) ---------------------------------
APP_DIR="${APP_DIR:-/var/www/html/thriive}"
APP_USER="${APP_USER:-thriive}"
# HOST: the IP or hostname to serve on. Pass it however you like — all three names
# work: HOST=, SERVER_IP=, or DOMAIN=. Leave blank to auto-detect the EC2 public IP.
#   sudo SERVER_IP=13.234.56.78 bash deploy/setup.sh
HOST="${HOST:-${SERVER_IP:-${DOMAIN:-}}}"
# HTTPS: 'false' (default) = plain-HTTP demo on a bare IP; 'true' enforces SSL
# redirect + secure cookies (needs a real domain + certbot).
ENABLE_HTTPS="${ENABLE_HTTPS:-false}"
DB_NAME="${DB_NAME:-thriive}"
DB_USER="${DB_USER:-thriive}"
DB_PASSWORD="${DB_PASSWORD:-change-me-in-env}"
NODE_MAJOR="${NODE_MAJOR:-20}"
PG_MAJOR="${PG_MAJOR:-17}"

BACKEND="$APP_DIR/backend"
FRONTEND="$APP_DIR/frontend"
LOG_DIR="/var/log/thriive"

# Gunicorn worker processes; default scales to the instance CPU count (gthread
# workers, 4 threads each). Capped so DB connections stay well under Postgres's
# max_connections=200 set below.
GUNICORN_WORKERS="${GUNICORN_WORKERS:-$((2 * $(nproc) + 1))}"
[ "$GUNICORN_WORKERS" -gt 24 ] && GUNICORN_WORKERS=24

# --- Resolve host + HTTPS mode --------------------------------------------------
# Remember whether the caller passed a host explicitly — an existing .env is only
# rewritten in that case (an auto-detected IP must never clobber a real domain).
if [ -n "$HOST" ]; then HOST_GIVEN=1; else HOST_GIVEN=0; fi
if [ -z "$HOST" ]; then
    # No host given — auto-detect: EC2 IMDSv2, then a public echo, then local IP.
    TOKEN="$(curl -s -X PUT 'http://169.254.169.254/latest/api/token' \
        -H 'X-aws-ec2-metadata-token-ttl-seconds: 60' 2>/dev/null || true)"
    HOST="$(curl -s -H "X-aws-ec2-metadata-token: $TOKEN" \
        http://169.254.169.254/latest/meta-data/public-ipv4 2>/dev/null || true)"
    [ -z "$HOST" ] && HOST="$(curl -s https://checkip.amazonaws.com 2>/dev/null | tr -d '\n' || true)"
    [ -z "$HOST" ] && HOST="$(hostname -I | awk '{print $1}')"
fi
# DOMAIN is the canonical name used in the config templates below.
DOMAIN="$HOST"

if [ "$ENABLE_HTTPS" = "true" ]; then
    SSL_FLAG="True";  SCHEME="https"
else
    SSL_FLAG="False"; SCHEME="http"
fi

echo ">>> Thriive setup — APP_DIR=$APP_DIR HOST=$DOMAIN HTTPS=$ENABLE_HTTPS"

# --- 1. Base system packages ----------------------------------------------------
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y \
    python3 python3-venv python3-dev python3-pip \
    build-essential libpq-dev \
    redis-server nginx supervisor \
    curl ca-certificates gnupg lsb-release \
    certbot python3-certbot-nginx

# --- 2. PostgreSQL. Recent Ubuntu (25.x) ships postgresql-17 in its own archive;
#        try that first, fall back to the PGDG repo (needed on 24.04 LTS), then to
#        the distro default so a brand-new release never hard-fails the deploy. ---
if ! command -v psql >/dev/null; then
    apt-get install -y "postgresql-$PG_MAJOR" || {
        echo ">>> postgresql-$PG_MAJOR not in distro repos — adding PGDG."
        install -d /usr/share/postgresql-common/pgdg
        curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc \
            -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc
        echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] \
https://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" \
            > /etc/apt/sources.list.d/pgdg.list
        apt-get update -y || true
        apt-get install -y "postgresql-$PG_MAJOR" || apt-get install -y postgresql
    }
fi
systemctl enable --now postgresql

# --- 2b. PostgreSQL tuning scaled to instance RAM. Stock config assumes a tiny
#         box (shared_buffers=128MB, max_connections=100) — far too small for the
#         transaction volumes this app aggregates. Ubuntu's postgresql.conf
#         includes conf.d/ by default; restart applies shared_buffers. ----------
PG_VER="$(ls /etc/postgresql 2>/dev/null | sort -V | tail -1 || true)"
if [ -n "$PG_VER" ]; then
    RAM_MB="$(free -m | awk '/^Mem:/{print $2}')"
    MAINT_MB=$(( RAM_MB / 16 )); [ "$MAINT_MB" -gt 512 ] && MAINT_MB=512
    mkdir -p "/etc/postgresql/$PG_VER/main/conf.d"
    cat > "/etc/postgresql/$PG_VER/main/conf.d/thriive.conf" <<PGCONF
# Thriive tuning — written by deploy/setup.sh for a ${RAM_MB}MB-RAM instance.
# Re-running setup.sh regenerates this file; hand-edits go in a separate file.
max_connections = 200
shared_buffers = $(( RAM_MB / 4 ))MB
effective_cache_size = $(( RAM_MB * 3 / 4 ))MB
work_mem = 16MB
maintenance_work_mem = ${MAINT_MB}MB
wal_buffers = 16MB
random_page_cost = 1.1
effective_io_concurrency = 200
PGCONF
    systemctl restart postgresql
fi

# --- 3. Node.js + npm (Vite 6 / React 19 need Node >= NODE_MAJOR) ----------------
# Prefer the distro packages (recent Ubuntu ships Node 20+); only fall back to
# NodeSource if that's missing or too old (and NodeSource may lag new codenames).
apt-get install -y nodejs npm || true
if ! command -v node >/dev/null || \
   [ "$(node -v | sed 's/v\([0-9]*\).*/\1/')" -lt "$NODE_MAJOR" ]; then
    apt-get remove -y npm || true          # avoid clashing with NodeSource's bundled npm
    curl -fsSL "https://deb.nodesource.com/setup_${NODE_MAJOR}.x" | bash -
    apt-get install -y nodejs
fi

# --- 4. Application user + directory ownership ----------------------------------
id -u "$APP_USER" &>/dev/null || useradd -r -m -s /bin/bash "$APP_USER"
mkdir -p "$APP_DIR" "$LOG_DIR"
# www-data (nginx) needs to read the built static/media files.
chown -R "$APP_USER:www-data" "$APP_DIR"
chown -R "$APP_USER:$APP_USER" "$LOG_DIR"
chmod 750 "$LOG_DIR"

# --- 4b. Sudoers: deploy.sh (run as $APP_USER) restarts the Supervisor group.
#         Exact commands only — modern sudo forbids wildcards in arguments, and
#         ':' is a sudoers metacharacter so it's escaped. Validate in a temp
#         file first: a bad file in /etc/sudoers.d breaks sudo for the box. ----
SUDOERS_TMP="$(mktemp)"
cat > "$SUDOERS_TMP" <<EOF
$APP_USER ALL=(root) NOPASSWD: /usr/bin/supervisorctl restart thriive\:, /usr/bin/supervisorctl status thriive\:
EOF
visudo -cf "$SUDOERS_TMP"
install -m 440 -o root -g root "$SUDOERS_TMP" /etc/sudoers.d/thriive
rm -f "$SUDOERS_TMP"

# --- 5. PostgreSQL role + database ----------------------------------------------
# The password goes in as a psql variable and is quoted with format(%L), so any
# character (quotes, |, &, $) is safe — never interpolated into the SQL text.
sudo -u postgres psql -v ON_ERROR_STOP=1 -v db_password="$DB_PASSWORD" <<SQL
SELECT format('CREATE ROLE $DB_USER LOGIN PASSWORD %L', :'db_password')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '$DB_USER')\gexec
SELECT 'CREATE DATABASE $DB_NAME OWNER $DB_USER'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '$DB_NAME')\gexec
ALTER DATABASE $DB_NAME OWNER TO $DB_USER;
SQL

# --- 6. Production .env (created once; edit it, then re-run deploy.sh) -----------
if [ ! -f "$BACKEND/.env" ]; then
    echo ">>> Writing $BACKEND/.env from template — REVIEW SECRETS before going live."
    # sed treats \, & and the | delimiter specially in the replacement — escape
    # them so a strong password can't corrupt the .env.
    DB_PASSWORD_ESC="$(printf '%s' "$DB_PASSWORD" | sed -e 's/[\\&|]/\\&/g')"
    sed -e "s|__DB_NAME__|$DB_NAME|" \
        -e "s|__DB_USER__|$DB_USER|" \
        -e "s|__DB_PASSWORD__|$DB_PASSWORD_ESC|" \
        -e "s|__DOMAIN__|$DOMAIN|" \
        -e "s|__SSL__|$SSL_FLAG|" \
        -e "s|__SCHEME__|$SCHEME|" \
        "$APP_DIR/deploy/env.prod.example" > "$BACKEND/.env"
    # A real random SECRET_KEY.
    SECRET="$(python3 -c 'import secrets; print(secrets.token_urlsafe(64))')"
    sed -i "s|__SECRET_KEY__|$SECRET|" "$BACKEND/.env"
    chown "$APP_USER:$APP_USER" "$BACKEND/.env"
    chmod 600 "$BACKEND/.env"
elif [ "$HOST_GIVEN" = "1" ]; then
    # Re-run with an explicit host (the documented demo→HTTPS upgrade path):
    # refresh the host + TLS keys in place. Everything else in .env is preserved.
    echo ">>> Updating host/HTTPS keys in existing $BACKEND/.env for $DOMAIN."
    sed -i \
        -e "s|^ALLOWED_HOSTS=.*|ALLOWED_HOSTS=$DOMAIN,localhost,127.0.0.1|" \
        -e "s|^SECURE_SSL_REDIRECT=.*|SECURE_SSL_REDIRECT=$SSL_FLAG|" \
        -e "s|^SESSION_COOKIE_SECURE=.*|SESSION_COOKIE_SECURE=$SSL_FLAG|" \
        -e "s|^CSRF_COOKIE_SECURE=.*|CSRF_COOKIE_SECURE=$SSL_FLAG|" \
        -e "s|^CSRF_TRUSTED_ORIGINS=.*|CSRF_TRUSTED_ORIGINS=$SCHEME://$DOMAIN|" \
        -e "s|^CORS_ALLOWED_ORIGINS=.*|CORS_ALLOWED_ORIGINS=$SCHEME://$DOMAIN|" \
        "$BACKEND/.env"
else
    echo ">>> Existing $BACKEND/.env left untouched (no HOST/DOMAIN passed)."
fi

systemctl enable --now redis-server

# --- 7. Build + migrate (delegated to deploy.sh so redeploys share one path) ----
sudo -u "$APP_USER" APP_DIR="$APP_DIR" bash "$APP_DIR/deploy/deploy.sh" --skip-restart

# --- 7b. Seed the base RBAC roles (idempotent; required before first login) -----
sudo -u "$APP_USER" DJANGO_SETTINGS_MODULE=config.settings.prod \
    "$BACKEND/venv/bin/python" "$BACKEND/manage.py" seed_roles

# --- 8. Nginx ------------------------------------------------------------------
sed "s|__DOMAIN__|$DOMAIN|; s|__APP_DIR__|$APP_DIR|" \
    "$APP_DIR/deploy/nginx/thriive.conf" > /etc/nginx/sites-available/thriive
ln -sf /etc/nginx/sites-available/thriive /etc/nginx/sites-enabled/thriive
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx

# --- 9. Supervisor (gunicorn + celery worker + beat) ----------------------------
sed "s|__APP_DIR__|$APP_DIR|; s|__APP_USER__|$APP_USER|; s|__GUNICORN_WORKERS__|$GUNICORN_WORKERS|" \
    "$APP_DIR/deploy/supervisor/thriive.conf" > /etc/supervisor/conf.d/thriive.conf
supervisorctl reread
supervisorctl update
supervisorctl restart thriive:

# --- 10. Nightly logical DB backup, 14-day retention. For real DR, also ship
#          these off-box (e.g. aws s3 sync /var/backups/thriive s3://...). ------
mkdir -p /var/backups/thriive
chown postgres:postgres /var/backups/thriive
chmod 700 /var/backups/thriive
cat > /etc/cron.d/thriive-backup <<EOF
30 1 * * * postgres pg_dump -Fc $DB_NAME -f /var/backups/thriive/$DB_NAME-\$(date +\%F).dump && find /var/backups/thriive -name '*.dump' -mtime +14 -delete
EOF
chmod 644 /etc/cron.d/thriive-backup

cat <<DONE

======================================================================
 Thriive IMS deployed.
   App dir   : $APP_DIR
   Web       : $SCHEME://$DOMAIN/   (Gunicorn on 127.0.0.1:8000 behind Nginx)
   Mode      : HTTPS=$ENABLE_HTTPS
   Processes : supervisorctl status thriive:
   Logs      : $LOG_DIR/

 Next:
   1. Review secrets in  $BACKEND/.env
   2. Create an admin:    sudo -u $APP_USER $BACKEND/venv/bin/python \\
                            $BACKEND/manage.py createsuperuser
   3. Browse to           $SCHEME://$DOMAIN/
DONE

if [ "$ENABLE_HTTPS" != "true" ]; then
cat <<'NOTE'
   NOTE: Running in plain-HTTP demo mode (no TLS). When you have a domain:
         point it at this instance, then re-run:
           sudo DOMAIN=your.domain ENABLE_HTTPS=true bash deploy/setup.sh
           sudo certbot --nginx -d your.domain
NOTE
fi
echo "======================================================================"
