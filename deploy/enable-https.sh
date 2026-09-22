#!/usr/bin/env bash
# Run as root after inbound TCP 80 and 443 are reachable from the Internet.
set -euo pipefail
address="${1:?Usage: bash deploy/enable-https.sh PUBLIC_IPV4}"
python3 -c 'import ipaddress, sys; assert ipaddress.ip_address(sys.argv[1]).version == 4' "$address"
deploy_dir="$(cd "$(dirname "$0")" && pwd)"
certbot=/opt/xuguangji/certbot/bin/certbot

# Validate the HTTP challenge with staging before requesting a trusted certificate.
"$certbot" certonly --non-interactive --agree-tos --register-unsafely-without-email \
    --staging --config-dir /etc/letsencrypt-staging \
    --work-dir /var/lib/letsencrypt-staging --logs-dir /var/log/letsencrypt-staging \
    --preferred-profile shortlived --webroot --webroot-path /var/www/xuguangji-acme \
    --ip-address "$address" --cert-name "$address"
"$certbot" certonly --non-interactive --agree-tos --register-unsafely-without-email \
    --preferred-profile shortlived --webroot --webroot-path /var/www/xuguangji-acme \
    --ip-address "$address" --cert-name "$address"

install -m 644 "$deploy_dir/nginx-app.conf" /etc/nginx/snippets/xuguangji-app.conf
cp /etc/nginx/sites-available/xuguangji /etc/nginx/sites-available/xuguangji.previous
sed "s/__PUBLIC_HOST__/$address/g" "$deploy_dir/nginx.conf.template" > /etc/nginx/sites-available/xuguangji
if ! nginx -t; then
    cp /etc/nginx/sites-available/xuguangji.previous /etc/nginx/sites-available/xuguangji
    exit 1
fi
systemctl reload nginx
install -d -m 755 /etc/letsencrypt/renewal-hooks/deploy
install -m 755 "$deploy_dir/reload-nginx.sh" /etc/letsencrypt/renewal-hooks/deploy/xuguangji-nginx
install -m 644 "$deploy_dir/systemd/xuguangji-cert-renew.service" /etc/systemd/system/
install -m 644 "$deploy_dir/systemd/xuguangji-cert-renew.timer" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now xuguangji-cert-renew.timer
"$certbot" renew --dry-run --run-deploy-hooks
