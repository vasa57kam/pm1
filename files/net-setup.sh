#!/usr/bin/env bash
# Собирает конфиг nginx только на СВОБОДНЫХ портах. 2096 не трогаем — его держит x-ui.
set -uo pipefail
APP=/opt/proxy-manager; cd "$APP" || exit 1
read -r DOMAIN CERT KEY <<<"$(./venv/bin/python - <<'PY'
import common as cm
s=cm.S(); c,k=cm.tlspaths(s)
print((s.get("domain") or "-"),(c or "-"),(k or "-"))
PY
)"
[ "$DOMAIN" = "-" ] && DOMAIN=""; [ "$CERT" = "-" ] && CERT=""; [ "$KEY" = "-" ] && KEY=""
IP=$(./venv/bin/python -c "import common as c;print(c.server_ip())" 2>/dev/null)
LOC=$(hostname -I 2>/dev/null | awk '{print $1}'); [ -z "$IP" ] && IP="$LOC"
SN="${DOMAIN:-$IP}"
if [ -z "$CERT" ] || [ ! -f "$CERT" ] || [ ! -f "$KEY" ]; then
  SANS="IP:$IP,IP:127.0.0.1"; [ -n "$LOC" ] && [ "$LOC" != "$IP" ] && SANS="$SANS,IP:$LOC"
  [ -n "$DOMAIN" ] && SANS="DNS:$DOMAIN,$SANS"
  openssl req -x509 -newkey rsa:2048 -nodes -days 3650 -keyout /etc/pm-web/self.key \
    -out /etc/pm-web/self.crt -subj "/CN=$SN" -addext "subjectAltName=$SANS" 2>/dev/null
  chmod 600 /etc/pm-web/self.key; CERT=/etc/pm-web/self.crt; KEY=/etc/pm-web/self.key
fi
echo "Сертификат: $CERT"
cat > /etc/nginx/sites-available/proxy-manager <<NG
server { listen 80 default_server; server_name ${DOMAIN:-_};
  location /.well-known/acme-challenge/ { root /var/www/certbot; }
  location / { return 301 https://\$host\$request_uri; } }
server { listen 443 ssl default_server; server_name ${DOMAIN:-_};
  ssl_certificate ${CERT}; ssl_certificate_key ${KEY}; ssl_protocols TLSv1.2 TLSv1.3;
  client_max_body_size 4096m;
  location / { proxy_pass http://127.0.0.1:8002; proxy_set_header Host \$host;
    proxy_set_header X-Real-IP \$remote_addr; proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto https; } }
server { listen 8443 ssl; server_name ${DOMAIN:-_};
  ssl_certificate ${CERT}; ssl_certificate_key ${KEY}; ssl_protocols TLSv1.2 TLSv1.3;
  client_max_body_size 4096m;
  location / { proxy_pass http://127.0.0.1:8003; proxy_set_header Host \$host;
    proxy_set_header X-Real-IP \$remote_addr; proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto https; } }
server { listen 2087 ssl; server_name ${DOMAIN:-_};
  ssl_certificate ${CERT}; ssl_certificate_key ${KEY}; ssl_protocols TLSv1.2 TLSv1.3;
  location / { proxy_pass http://127.0.0.1:7681; proxy_http_version 1.1;
    proxy_set_header Upgrade \$http_upgrade; proxy_set_header Connection "upgrade";
    proxy_set_header Host \$host; proxy_read_timeout 86400; proxy_send_timeout 86400; } }
server { listen 2083 ssl; server_name ${DOMAIN:-_};
  ssl_certificate ${CERT}; ssl_certificate_key ${KEY}; ssl_protocols TLSv1.2 TLSv1.3;
  client_max_body_size 4096m;
  location / { proxy_pass http://127.0.0.1:8080; proxy_set_header Host \$host;
    proxy_set_header X-Forwarded-Proto https; proxy_read_timeout 3600; } }
NG
rm -f /etc/nginx/sites-enabled/default /etc/nginx/sites-enabled/acme /etc/nginx/sites-enabled/early /etc/nginx/sites-enabled/bootstrap
ln -sf /etc/nginx/sites-available/proxy-manager /etc/nginx/sites-enabled/proxy-manager
nginx -t || { echo "ОШИБКА СИНТАКСИСА"; exit 1; }
systemctl restart nginx
sleep 2
./venv/bin/python - <<PY
import common as cm
d="${DOMAIN}"; ip="${IP}"; base=d or ip
cm.setS({"public_url":"https://"+base,"admin_url":"https://"+base+":8443","sub_url_base":"https://"+base})
print("URL: https://"+base+"  (подписки на 443, порт 2096 оставлен x-ui)")
try: print("Прокси:",cm.apply_proxy_tls()[1])
except Exception as e: print("Прокси:",e)
try: cm.apply_web_creds()
except Exception as e: print("creds:",e)
PY
systemctl restart rescue-agent 2>/dev/null || true
echo "Готово: $SN"
