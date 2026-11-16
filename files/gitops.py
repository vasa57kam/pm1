import os,re,io,json,time,shutil,zipfile,subprocess,tempfile,hashlib
from pathlib import Path
import common as cm
BASE=cm.BASE
LOG="/opt/proxy-manager/git_result.txt"
def cfg():
    s=cm.S()
    return {"repo":(s.get("git_repo") or "").strip(),"branch":(s.get("git_branch") or "main").strip(),
            "token":(s.get("git_token") or "").strip()}
def _sh(c,t=180):
    try:
        r=subprocess.run(c,shell=True,capture_output=True,text=True,timeout=t)
        return (r.stdout+r.stderr).strip()
    except Exception as e: return "err: %s"%e
def _url(c):
    r=c["repo"]
    if not r: return ""
    r=r.replace("git@github.com:","https://github.com/").removesuffix(".git")
    if c["token"] and r.startswith("https://"):
        r=r.replace("https://","https://"+c["token"]+"@")
    return r
def clone(c=None):
    c=c or cfg(); u=_url(c)
    if not u: return None,"Репозиторий не указан"
    d=tempfile.mkdtemp(prefix="pmgit_")
    out=_sh(f"git clone --depth 1 -b {c['branch']} '{u}' '{d}/repo' 2>&1",180)
    if not os.path.isdir(d+"/repo"): return None,"clone не удался: "+out[:400]
    return d+"/repo",out[:300]
def _targets():
    t={}
    for p in sorted(BASE.glob("*.py")):
        if p.name!="gitops.py": t[p.name]=p
    for p in sorted((BASE/"templates").glob("*.html")): t["templates/"+p.name]=p
    ex=BASE/"extension"
    if ex.is_dir():
        for p in sorted(ex.rglob("*")):
            if p.is_file(): t["extension/"+str(p.relative_to(ex))]=p
    ns=BASE/"net-setup.sh"
    if ns.is_file(): t["net-setup.sh"]=ns
    return t
def check(c=None):
    c=c or cfg()
    if not c["repo"]: return "Репозиторий не указан"
    rp,out=clone(c)
    if not rp: return out
    lines=["Репозиторий склонирован: "+c["repo"]+" ("+c["branch"]+")",""]
    diff=0
    for rel,local in _targets().items():
        rem=Path(rp)/rel
        if not rem.is_file(): lines.append("  только локально: "+rel); continue
        a=hashlib.md5(local.read_bytes()).hexdigest(); b=hashlib.md5(rem.read_bytes()).hexdigest()
        if a!=b: lines.append("  ОТЛИЧАЕТСЯ: "+rel); diff+=1
    for rel in ("common.py","admin_app.py","web_app.py","bot.py","monitor.py","xui_api.py","gitops.py","install.sh"):
        if (Path(rp)/rel).is_file() and rel not in _targets(): lines.append("  новое в репо: "+rel); diff+=1
    lines.append(""); lines.append("Отличий: "+str(diff))
    shutil.rmtree(Path(rp).parent,ignore_errors=True)
    return "\n".join(lines)
def update(full=False):
    c=cfg()
    if not c["repo"]: return False,"Репозиторий не указан"
    rp,out=clone(c)
    if not rp: return False,out
    L=["Обновление из "+c["repo"],""]
    if full and (Path(rp)/"install.sh").is_file():
        L.append("ПОЛНАЯ переустановка через install.sh из репо")
        shutil.rmtree(Path(rp).parent,ignore_errors=True)
        return True,"RUN_INSTALLER"
    bd=BASE/"backups"/("git-"+time.strftime("%Y%m%d_%H%M%S")); bd.mkdir(parents=True,exist_ok=True)
    applied=[]
    for rel in list(_targets().keys())+["gitops.py"]:
        rem=Path(rp)/rel
        if not rem.is_file(): continue
        loc=BASE/rel
        if loc.is_file():
            b=bd/rel; b.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(loc,b)
        loc.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(rem,loc); applied.append(rel)
    L.append("Применено файлов: "+str(len(applied)))
    L+=["  "+x for x in applied]
    chk=_sh(f"cd {BASE} && ./venv/bin/python -c 'import common,xui_api,admin_app,web_app,bot,monitor' 2>&1",90)
    if chk:
        L+=["","❌ ПРОВЕРКА ИМПОРТА ПРОВАЛЕНА:",chk[:1500],"","Откат..."]
        for rel in applied:
            b=bd/rel
            if b.is_file(): shutil.copy2(b,BASE/rel)
        _sh("systemctl restart proxy-admin proxy-web proxy-bot proxy-monitor",60)
        shutil.rmtree(Path(rp).parent,ignore_errors=True)
        return False,"\n".join(L)
    L.append("✅ импорт OK")
    if (Path(rp)/"net-setup.sh").is_file(): os.chmod(BASE/"net-setup.sh",0o755)
    _sh("systemctl restart proxy-admin proxy-web proxy-bot proxy-monitor",60)
    time.sleep(6)
    a=_sh("curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8003/login",20)
    b=_sh("curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8002/",20)
    L.append(f"Здоровье: admin={a} web={b}")
    if a!="200" or b!="200":
        L+=["❌ сервисы не поднялись — откат"]
        for rel in applied:
            bb=bd/rel
            if bb.is_file(): shutil.copy2(bb,BASE/rel)
        _sh("systemctl restart proxy-admin proxy-web proxy-bot proxy-monitor",60)
        shutil.rmtree(Path(rp).parent,ignore_errors=True)
        return False,"\n".join(L)
    L.append("✅ ОБНОВЛЕНИЕ УСПЕШНО. Бэкап: "+str(bd))
    shutil.rmtree(Path(rp).parent,ignore_errors=True)
    return True,"\n".join(L)
BOOT = r'''#!/usr/bin/env bash
# Proxy Manager — самодостаточный установщик (сгенерирован из рабочей системы)
set -uo pipefail
APP=/opt/proxy-manager
LOG=/root/pm-install.log
[ "$(id -u)" = 0 ] || { echo "нужен root"; exit 1; }
exec > >(tee -a "$LOG") 2>&1
WP0=$(tr -dc 'A-Za-z0-9' </dev/urandom | head -c 16)
apt-get update -y
DEBIAN_FRONTEND=noninteractive apt-get install -y python3 python3-venv python3-pip nginx certbot \
  curl git zip tar openssl ufw ca-certificates openssh-client dnsutils iproute2
mkdir -p "$APP/templates" "$APP/extension" /etc/pm-web /var/www/certbot /opt/rescue-agent
PUB=""; for u in https://api.ipify.org https://ifconfig.me/ip https://icanhazip.com; do
  v=$(curl -4 -s --max-time 8 "$u"|tr -d '[:space:]'); case "$v" in *.*.*.*) PUB="$v";break;; esac; done
LOC=$(hostname -I 2>/dev/null|awk '{print $1}'); [ -z "$PUB" ] && PUB="$LOC"; [ -z "$PUB" ] && PUB=127.0.0.1
DOMAIN="${DOMAIN:-}"
echo "IP: $PUB  локальный: $LOC"
printf 'admin\n%s\n' "$WP0" > /etc/pm-web/cred; chmod 600 /etc/pm-web/cred
SANS="IP:$PUB,IP:127.0.0.1"; [ -n "$LOC" ] && [ "$LOC" != "$PUB" ] && SANS="$SANS,IP:$LOC"
[ -n "$DOMAIN" ] && SANS="DNS:$DOMAIN,$SANS"
openssl req -x509 -newkey rsa:2048 -nodes -days 3650 -keyout /etc/pm-web/self.key \
  -out /etc/pm-web/self.crt -subj "/CN=${DOMAIN:-$PUB}" -addext "subjectAltName=$SANS" 2>/dev/null
chmod 600 /etc/pm-web/self.key
command -v ttyd >/dev/null 2>&1 || { curl -fsSL -o /usr/local/bin/ttyd https://github.com/tsl0922/ttyd/releases/latest/download/ttyd.x86_64 && chmod +x /usr/local/bin/ttyd; }
command -v filebrowser >/dev/null 2>&1 || curl -fsSL https://raw.githubusercontent.com/filebrowser/get/master/get.sh | bash || true
command -v filebrowser >/dev/null 2>&1 || { curl -fsSL -o /tmp/fb.tgz https://github.com/filebrowser/filebrowser/releases/latest/download/linux-amd64-filebrowser.tar.gz && tar -xzf /tmp/fb.tgz -C /usr/local/bin filebrowser && chmod +x /usr/local/bin/filebrowser; } || true
cat > /etc/systemd/system/web-term.service <<U
[Unit]
Description=Web Terminal
After=network-online.target
[Service]
ExecStart=/usr/local/bin/ttyd -W -i 127.0.0.1 -p 7681 -c admin:${WP0} /bin/bash
Restart=always
RestartSec=3
[Install]
WantedBy=multi-user.target
U
filebrowser config init -d /etc/pm-web/fb.db >/dev/null 2>&1 || true
filebrowser users add admin "$WP0" --perm.admin -d /etc/pm-web/fb.db >/dev/null 2>&1 || true
cat > /etc/systemd/system/web-files.service <<U
[Unit]
Description=Web Files
After=network-online.target
[Service]
ExecStart=/usr/local/bin/filebrowser -r / -a 127.0.0.1 -p 8080 -d /etc/pm-web/fb.db
Restart=always
RestartSec=3
[Install]
WantedBy=multi-user.target
U
cat > /etc/nginx/sites-available/proxy-manager <<NG
server { listen 80 default_server; server_name _;
  location /.well-known/acme-challenge/ { root /var/www/certbot; }
  location / { return 200 "installing..."; } }
server { listen 2087 ssl default_server; server_name _;
  ssl_certificate /etc/pm-web/self.crt; ssl_certificate_key /etc/pm-web/self.key;
  location / { proxy_pass http://127.0.0.1:7681; proxy_http_version 1.1;
    proxy_set_header Upgrade \$http_upgrade; proxy_set_header Connection "upgrade";
    proxy_set_header Host \$host; proxy_read_timeout 86400; } }
server { listen 2083 ssl default_server; server_name _;
  ssl_certificate /etc/pm-web/self.crt; ssl_certificate_key /etc/pm-web/self.key;
  client_max_body_size 4096m;
  location / { proxy_pass http://127.0.0.1:8080; proxy_set_header Host \$host; } }
NG
rm -f /etc/nginx/sites-enabled/default
ln -sf /etc/nginx/sites-available/proxy-manager /etc/nginx/sites-enabled/proxy-manager
nginx -t && systemctl enable --now nginx && systemctl restart nginx
systemctl daemon-reload && systemctl enable --now web-term web-files
command -v ufw >/dev/null && { for p in 22 2222 80 443 2087 2083 8443 8444 2096; do ufw allow $p/tcp; done; ufw allow 20000:21000/tcp; } || true
echo "### КОНСОЛЬ https://${PUB}:2087  admin / ${WP0}"
echo "### ФАЙЛЫ   https://${PUB}:2083"
cd "$APP"
'''
TAIL = r'''
chmod +x "$APP/net-setup.sh" 2>/dev/null || true
chmod 700 /opt/rescue-agent
cat > /etc/systemd/system/rescue-agent.service <<'U'
[Unit]
Description=Rescue Agent
After=network-online.target
[Service]
ExecStart=/usr/bin/python3 /opt/rescue-agent/agent.py
Restart=always
RestartSec=3
[Install]
WantedBy=multi-user.target
U
systemctl daemon-reload && systemctl enable --now rescue-agent
python3 -m venv venv || exit 1
./venv/bin/pip install -q --upgrade pip
./venv/bin/pip install -q "fastapi>=0.110" "uvicorn>=0.29" "aiogram>=3.7,<4" requests aiosqlite \
  "apscheduler>=3.10,<4" jinja2 python-multipart passlib "bcrypt==4.0.1" "pydantic>=2" qrcode pillow cryptography
./venv/bin/python -c "import common;common.init_db();print('БД ok')" || exit 1
./venv/bin/python -c "import common as c;c.setS({'web_user':'admin','web_pass':'__WP__','_fb_prev':'admin','server_ip':'__IP__'})"
[ -n "$DOMAIN" ] && ./venv/bin/python -c "import common;common.setS({'domain':'$DOMAIN'})"
for m in common xui_api admin_app web_app bot monitor gitops; do
  ./venv/bin/python -c "import $m" 2>/dev/null && echo "  OK $m" || echo "  FAIL $m"; done
for pair in admin:8003 web:8002; do n=${pair%%:*}; p=${pair##*:}
cat > /etc/systemd/system/proxy-$n.service <<U
[Unit]
Description=Proxy Manager $n
After=network-online.target
[Service]
WorkingDirectory=/opt/proxy-manager
ExecStart=/opt/proxy-manager/venv/bin/uvicorn ${n}_app:app --host 127.0.0.1 --port $p
Restart=always
RestartSec=3
[Install]
WantedBy=multi-user.target
U
done
for n in bot monitor; do
cat > /etc/systemd/system/proxy-$n.service <<U
[Unit]
Description=Proxy Manager $n
After=network-online.target
[Service]
WorkingDirectory=/opt/proxy-manager
ExecStart=/opt/proxy-manager/venv/bin/python $n.py
Restart=always
RestartSec=5
[Install]
WantedBy=multi-user.target
U
done
systemctl daemon-reload && systemctl enable proxy-admin proxy-web proxy-bot proxy-monitor >/dev/null 2>&1
systemctl restart proxy-admin proxy-web proxy-bot proxy-monitor
sleep 4
bash "$APP/net-setup.sh"
sleep 2
for pp in 80 443 8443 2087 2083; do ss -tln|grep -q ":$pp " && echo "  $pp ok" || echo "  $pp НЕТ"; done
B=$(./venv/bin/python -c "import common as c;print(c.host(c.S()))")
WP=$(./venv/bin/python -c "import common as c;print(c.S()['web_pass'])")
RT=$(./venv/bin/python -c "import common as c;print(c.rescue_token())")
echo "============================================================"
echo " ГОТОВО: https://${B}/  админка https://${B}:8443 (admin/admin)"
echo " консоль https://${B}:2087  файлы https://${B}:2083  admin / ${WP}"
echo " резерв  https://${B}:8444/${RT}/"
echo "============================================================"
'''
def build_installer():
    parts=[BOOT]
    files={}
    for rel,p in _targets().items(): files[rel]=p.read_bytes()
    g=BASE/"gitops.py"
    if g.is_file(): files["gitops.py"]=g.read_bytes()
    ra=Path("/opt/rescue-agent/agent.py")
    if ra.is_file(): files["__rescue__"]=ra.read_bytes()
    for rel,data in files.items():
        tag="PMF_"+hashlib.md5(rel.encode()).hexdigest()[:12].upper()
        if rel=="__rescue__":
            parts.append("mkdir -p /opt/rescue-agent\ncat > /opt/rescue-agent/agent.py <<'%s'\n"%tag)
        else:
            d=os.path.dirname(rel)
            if d: parts.append("mkdir -p \"$APP/%s\"\n"%d)
            parts.append("cat > \"$APP/%s\" <<'%s'\n"%(rel,tag))
        parts.append(data.decode("utf-8","replace"))
        if not data.endswith(b"\n"): parts.append("\n")
        parts.append(tag+"\n")
    tail=TAIL.replace("__WP__","$WP0").replace("__IP__","$PUB")
    parts.append(tail)
    return "".join(parts)
def export_zip():
    buf=io.BytesIO()
    inst=build_installer()
    with zipfile.ZipFile(buf,"w",zipfile.ZIP_DEFLATED) as z:
        z.writestr("install.sh",inst)
        for rel,p in _targets().items(): z.writestr("files/"+rel,p.read_bytes())
        g=BASE/"gitops.py"
        if g.is_file(): z.writestr("files/gitops.py",g.read_bytes())
        ra=Path("/opt/rescue-agent/agent.py")
        if ra.is_file(): z.writestr("files/rescue-agent.py",ra.read_bytes())
        z.writestr("README.md","# Proxy Manager\n\n"
          "## Развернуть с нуля\n```\nbash install.sh\n```\n"
          "или с доменом: `DOMAIN=example.com bash install.sh`\n\n"
          "## Обновить работающую систему\nАдминка → 🐙 GitHub → «Обновить файлы».\n\n"
          "`install.sh` самодостаточный: внутри все модули, шаблоны и расширение.\n"
          "Каталог `files/` — те же файлы россыпью, для точечного обновления.\n")
    return buf.getvalue()
