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

# --- Resolve host + HTTPS mode --------------------------------------------------
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

# --- 5. PostgreSQL role + database ----------------------------------------------
sudo -u postgres psql -v ON_ERROR_STOP=1 <<SQL
DO \$\$
BEGIN
   IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '$DB_USER') THEN
      CREATE ROLE $DB_USER LOGIN PASSWORD '$DB_PASSWORD';
   END IF;
END
\$\$;
SELECT 'CREATE DATABASE $DB_NAME OWNER $DB_USER'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '$DB_NAME')\gexec
ALTER DATABASE $DB_NAME OWNER TO $DB_USER;
SQL

# --- 6. Production .env (created once; edit it, then re-run deploy.sh) -----------
if [ ! -f "$BACKEND/.env" ]; then
    echo ">>> Writing $BACKEND/.env from template — REVIEW SECRETS before going live."
    sed -e "s|__DB_NAME__|$DB_NAME|" \
        -e "s|__DB_USER__|$DB_USER|" \
        -e "s|__DB_PASSWORD__|$DB_PASSWORD|" \
        -e "s|__DOMAIN__|$DOMAIN|" \
        -e "s|__SSL__|$SSL_FLAG|" \
        -e "s|__SCHEME__|$SCHEME|" \
        "$APP_DIR/deploy/env.prod.example" > "$BACKEND/.env"
    # A real random SECRET_KEY.
    SECRET="$(python3 -c 'import secrets; print(secrets.token_urlsafe(64))')"
    sed -i "s|__SECRET_KEY__|$SECRET|" "$BACKEND/.env"
    chown "$APP_USER:$APP_USER" "$BACKEND/.env"
    chmod 600 "$BACKEND/.env"
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
sed "s|__APP_DIR__|$APP_DIR|; s|__APP_USER__|$APP_USER|" \
    "$APP_DIR/deploy/supervisor/thriive.conf" > /etc/supervisor/conf.d/thriive.conf
supervisorctl reread
supervisorctl update
supervisorctl restart thriive:

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
