#!/usr/bin/env bash
#
# Thriive IMS — redeploy / update.
# Run as the app user after pulling new code. Installs deps, runs migrations,
# builds the frontend, collects static, and restarts the app processes.
#
#   sudo -u thriive bash /var/www/html/thriive/deploy/deploy.sh
#
# Pass --skip-restart to build without touching Supervisor (used by setup.sh,
# which restarts everything itself at the end).
set -euo pipefail

APP_DIR="${APP_DIR:-/var/www/html/thriive}"
BACKEND="$APP_DIR/backend"
FRONTEND="$APP_DIR/frontend"
export DJANGO_SETTINGS_MODULE="config.settings.prod"

SKIP_RESTART=0
[ "${1:-}" = "--skip-restart" ] && SKIP_RESTART=1

# --- Backend --------------------------------------------------------------------
cd "$BACKEND"
if [ ! -d venv ]; then
    python3 -m venv venv
fi
venv/bin/pip install --upgrade pip
venv/bin/pip install -r requirements/prod.txt
venv/bin/python manage.py migrate --noinput
venv/bin/python manage.py collectstatic --noinput

# --- Frontend -------------------------------------------------------------------
cd "$FRONTEND"
npm ci
npm run build

# --- Restart (skipped during first-time setup) ----------------------------------
if [ "$SKIP_RESTART" -eq 0 ]; then
    # Supervisor runs as root. As the app user we go through sudo -n (never
    # prompt) — the passwordless rule is installed by setup.sh.
    if [ "$(id -u)" -eq 0 ]; then
        supervisorctl restart thriive:
    elif ! sudo -n supervisorctl restart thriive:; then
        echo "!!! Restart failed: no passwordless sudo rule for supervisorctl." >&2
        echo "!!! Install it (once, as root) by re-running deploy/setup.sh, or:" >&2
        echo "!!!   echo 'thriive ALL=(root) NOPASSWD: /usr/bin/supervisorctl restart thriive*, /usr/bin/supervisorctl status thriive*' | sudo tee /etc/sudoers.d/thriive" >&2
        echo "!!!   sudo chmod 440 /etc/sudoers.d/thriive" >&2
        echo "!!! Then restart manually: sudo supervisorctl restart thriive:" >&2
        exit 1
    fi
    echo ">>> Restarted thriive: processes."
fi

echo ">>> Deploy complete."
