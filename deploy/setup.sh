#!/usr/bin/env bash
# EC2 bootstrap for Thriive IMS
# Run as root on a fresh Ubuntu 24.04 instance
set -euo pipefail

# --- System dependencies ---
apt-get update -y
apt-get install -y python3.12 python3.12-venv python3-pip \
    nodejs npm \
    postgresql-17 redis-server \
    nginx supervisor certbot python3-certbot-nginx \
    build-essential libpq-dev

# --- App user ---
id -u thriive &>/dev/null || useradd -m -s /bin/bash thriive

# --- Clone repo ---
mkdir -p /opt/thriive
chown thriive:thriive /opt/thriive

# --- Backend ---
cd /opt/thriive/backend
python3.12 -m venv venv
venv/bin/pip install --upgrade pip
venv/bin/pip install -r requirements/prod.txt
venv/bin/python manage.py migrate
venv/bin/python manage.py collectstatic --noinput
venv/bin/python manage.py seed_roles

# --- Frontend ---
cd /opt/thriive/frontend
npm ci
npm run build

# --- Nginx ---
cp /opt/thriive/deploy/nginx/thriive.conf /etc/nginx/sites-available/thriive
ln -sf /etc/nginx/sites-available/thriive /etc/nginx/sites-enabled/thriive
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx

# --- Supervisor ---
cp /opt/thriive/deploy/supervisor/thriive.conf /etc/supervisor/conf.d/thriive.conf
mkdir -p /var/log/thriive
chown -R thriive:thriive /var/log/thriive
supervisorctl reread && supervisorctl update

echo "Thriive IMS deployed successfully."
