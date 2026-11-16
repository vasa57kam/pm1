import json,sqlite3,time,secrets,hmac,hashlib,base64,io,zipfile,os,re,string,subprocess,socket,calendar
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import quote
import requests
from passlib.hash import bcrypt
BASE=Path(__file__).resolve().parent; DBP=BASE/"proxy_manager.db"
PRESETS={"Telegram":["telegram.org","t.me","telegra.ph","telesco.pe"],
"YouTube":["youtube.com","youtu.be","googlevideo.com","ytimg.com"],
"Instagram":["instagram.com","cdninstagram.com"],"Discord":["discord.com","discord.gg","discordapp.com","discord.media"],
"Twitter/X":["twitter.com","x.com","twimg.com","t.co"],"Facebook":["facebook.com","fbcdn.net"],
"WhatsApp":["whatsapp.com","whatsapp.net"],"Reddit":["reddit.com","redd.it"],
"Wikipedia":["wikipedia.org","wikimedia.org"],"Google":["google.com","gstatic.com","googleapis.com","googleusercontent.com"]}
DEF={"panel_name":"Proxy Manager","bot_token":"","admin_tg_id":"",
"xui_url":"http://127.0.0.1:2053","xui_user":"admin","xui_pass":"admin","xui_api_token":"","inbound_id":"1",
"domain":"","server_ip":"","sni":"","vless_port":"443","reality_pbk":"","reality_sid":"","fp":"chrome",
"billing_enabled":"0","price":"100","period_days":"30","billing_secret":secrets.token_hex(16),
"http_port_start":"20000","http_port_end":"21000","inbounds_cache":"{}","require_plan":"1",
"public_url":"","admin_url":"","sub_url_base":"","proxy_tls":"1","cert_mode":"auto",
"tls_cert":"","tls_key":"","le_email":"",
"web_user":"admin","web_pass":"","rescue_token":"",
"site_name":"Инфоструктура","site_tagline":"Проектируем, размещаем и сопровождаем серверы и веб-сервисы для малого и среднего бизнеса.",
"site_about":"","site_phone":"","site_email":"","site_inn":"","site_addr":"",
"site_years":"12","site_projects":"240","site_uptime":"99.9",
"guest_enabled":"0","guest_token":secrets.token_urlsafe(24),
"ext_presets":json.dumps(PRESETS,ensure_ascii=False),"ext_lists":json.dumps({"telegram_actual":"","all_ru_blocked":""})}
SCHEMA="""
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT);
CREATE TABLE IF NOT EXISTS admins(id INTEGER PRIMARY KEY AUTOINCREMENT,username TEXT UNIQUE,password_hash TEXT);
CREATE TABLE IF NOT EXISTS clients(id INTEGER PRIMARY KEY AUTOINCREMENT,tg_id TEXT UNIQUE,name TEXT,email TEXT UNIQUE,
 uuid TEXT,balance REAL DEFAULT 0,limit_gb REAL DEFAULT 0,used_bytes INTEGER DEFAULT 0,enabled INTEGER DEFAULT 1,
 notified INTEGER DEFAULT 0,paid_until INTEGER DEFAULT 0,ext_key TEXT UNIQUE,http_port INTEGER DEFAULT 0,
 http_user TEXT DEFAULT '',http_pass TEXT DEFAULT '',http_inbound_id INTEGER DEFAULT 0,inbound_id INTEGER DEFAULT 0,
 plan_id INTEGER DEFAULT 0,sub_id TEXT DEFAULT '',access_code TEXT DEFAULT '',created_at TEXT DEFAULT (datetime('now')));
CREATE TABLE IF NOT EXISTS payments(id INTEGER PRIMARY KEY AUTOINCREMENT,tg_id TEXT,amount REAL,source TEXT DEFAULT 'admin',
 status TEXT DEFAULT 'paid',external_id TEXT DEFAULT '',created_at TEXT DEFAULT (datetime('now')));
CREATE TABLE IF NOT EXISTS suggestions(id INTEGER PRIMARY KEY AUTOINCREMENT,ext_key TEXT,name TEXT,domains TEXT,created_at TEXT DEFAULT (datetime('now')));
CREATE TABLE IF NOT EXISTS registrations(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,phone TEXT,email TEXT DEFAULT '',
 tg_id TEXT DEFAULT '',comment TEXT DEFAULT '',code TEXT UNIQUE,status TEXT DEFAULT 'pending',client_id INTEGER DEFAULT 0,
 created_at TEXT DEFAULT (datetime('now')),decided_at TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS plans(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,price REAL DEFAULT 0,period_days INTEGER DEFAULT 30,
 limit_gb REAL DEFAULT 0,description TEXT DEFAULT '',enabled INTEGER DEFAULT 1,sort_order INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS promos(id INTEGER PRIMARY KEY AUTOINCREMENT,code TEXT UNIQUE,kind TEXT,value REAL DEFAULT 0,
 max_uses INTEGER DEFAULT 0,used_count INTEGER DEFAULT 0,expires_at INTEGER DEFAULT 0,enabled INTEGER DEFAULT 1,note TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS promo_uses(id INTEGER PRIMARY KEY AUTOINCREMENT,promo_id INTEGER,client_id INTEGER,detail TEXT,created_at TEXT DEFAULT (datetime('now')));
"""
@contextmanager
def db():
    c=sqlite3.connect(DBP,timeout=15); c.row_factory=sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL"); c.execute("PRAGMA busy_timeout=10000")
    try:
        yield c; c.commit()
    finally: c.close()
def rnd(n,up=False):
    al=(string.ascii_uppercase+string.digits) if up else (string.ascii_lowercase+string.digits)
    return "".join(secrets.choice(al) for _ in range(n))
def detect_ips():
    pub=""
    for u in ("https://api.ipify.org","https://ifconfig.me/ip","https://icanhazip.com"):
        try:
            r=requests.get(u,timeout=6); v=r.text.strip()
            if r.ok and re.match(r"^\d+\.\d+\.\d+\.\d+$",v): pub=v; break
        except Exception: pass
    loc=""
    try:
        o=subprocess.run("hostname -I",shell=True,capture_output=True,text=True,timeout=5).stdout.split()
        loc=o[0] if o else ""
    except Exception: pass
    if not loc:
        try: loc=socket.gethostbyname(socket.gethostname())
        except Exception: loc="127.0.0.1"
    return pub,loc
_IPC={"t":0,"pub":"","loc":""}
def ips(s=None):
    s=s or S()
    if _IPC["pub"] and time.time()-_IPC["t"]<600: return _IPC["pub"],_IPC["loc"]
    p,l=detect_ips(); _IPC.update(t=time.time(),pub=p,loc=l); return p,l
def server_ip(s=None):
    s=s or S(); m=(s.get("server_ip") or "").strip()
    if m: return m
    p,l=ips(s); return p or l or "127.0.0.1"
def init_db():
    with db() as c:
        c.executescript(SCHEMA)
        for k,v in DEF.items(): c.execute("INSERT OR IGNORE INTO settings VALUES(?,?)",(k,v))
        if not c.execute("SELECT 1 FROM admins LIMIT 1").fetchone():
            c.execute("INSERT INTO admins(username,password_hash) VALUES(?,?)",("admin",bcrypt.hash("admin")))
        if not c.execute("SELECT 1 FROM plans LIMIT 1").fetchone():
            c.executemany("INSERT INTO plans(name,price,period_days,limit_gb,description,sort_order) VALUES(?,?,?,?,?,?)",
              [("Старт",100,30,50,"Браузер и мессенджеры",1),("Стандарт",200,30,200,"На каждый день",2),("Безлимит",350,30,0,"Без лимита",3)])
        for r in [dict(x) for x in c.execute("SELECT id,sub_id,access_code FROM clients")]:
            if not r["sub_id"]: c.execute("UPDATE clients SET sub_id=? WHERE id=?",(rnd(16),r["id"]))
            if not r["access_code"]: c.execute("UPDATE clients SET access_code=? WHERE id=?",(rnd(6,True),r["id"]))
def S():
    s=dict(DEF)
    with db() as c:
        for r in c.execute("SELECT key,value FROM settings"): s[r["key"]]=r["value"]
    return s
def setS(d):
    with db() as c:
        c.executemany("INSERT INTO settings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",[(k,str(v)) for k,v in d.items()])
def clients():
    with db() as c: return [dict(r) for r in c.execute("SELECT * FROM clients ORDER BY id")]
def client(**kw):
    ok={"id","tg_id","email","ext_key","uuid","sub_id"}; cond={k:v for k,v in kw.items() if k in ok}
    if not cond: return None
    w=" AND ".join(f"{k}=?" for k in cond)
    with db() as c:
        r=c.execute(f"SELECT * FROM clients WHERE {w} LIMIT 1",tuple(cond.values())).fetchone()
        return dict(r) if r else None
def now(): return int(time.time())
def gb(b): return f"{(b or 0)/2**30:.2f}"
def xui(s,t=15):
    from xui_api import XUI
    return XUI(s["xui_url"],s["xui_user"],s["xui_pass"],s.get("xui_api_token",""),timeout=t)
def host(s): return s.get("domain") or server_ip(s)
def pbase(s): return (s.get("public_url") or f"https://{host(s)}").rstrip("/")
def cab(c,s): return f"{pbase(s)}/client/{c['tg_id']}"
def subbase(s): return (s.get("sub_url_base") or pbase(s)).rstrip("/")
def sub(c,s): return f"{subbase(s)}/sub/{c.get('sub_id') or c['tg_id']}"
def ib(c,s):
    try: i=int(c.get("inbound_id") or 0)
    except Exception: i=0
    return i or int(s["inbound_id"])
def ibcache(s,force=False):
    try: ca=json.loads(s.get("inbounds_cache") or "{}")
    except Exception: ca={}
    if not force and ca.get("_ts",0)>time.time()-300 and len(ca)>1: return ca
    try:
        new={"_ts":int(time.time())}
        for b in xui(s,10).get_inbounds():
            ss=b.get("streamSettings") or {}; st=b.get("settings") or {}
            if isinstance(ss,str): ss=json.loads(ss or "{}")
            if isinstance(st,str): st=json.loads(st or "{}")
            rs=ss.get("realitySettings") or {}; inner=rs.get("settings") or {}
            sn=rs.get("serverNames") or []; si=rs.get("shortIds") or []
            new[str(b.get("id"))]={"port":b.get("port"),"protocol":b.get("protocol"),"remark":b.get("remark") or "",
              "security":ss.get("security") or "","sni":next((v for v in sn if v),""),"pbk":inner.get("publicKey") or "",
              "sid":next((v for v in si if v),""),"fp":inner.get("fingerprint") or "chrome","spx":inner.get("spiderX") or "/",
              "encryption":st.get("encryption") or "","clients":len(st.get("clients") or [])}
        setS({"inbounds_cache":json.dumps(new,ensure_ascii=False)}); return new
    except Exception: return ca
def vless(c,s):
    p=ibcache(s).get(str(ib(c,s))) or {}
    enc=p.get("encryption") or "none"; pbk=p.get("pbk") or s.get("reality_pbk") or ""
    q={"type":"tcp","encryption":enc,"security":"reality" if pbk else "none",
       "sni":p.get("sni") or s.get("sni",""),"fp":p.get("fp") or s.get("fp","chrome"),"spx":p.get("spx") or "/"}
    if "mlkem768" in enc: q["support-x25519mlkem768"]="true"
    else: q["flow"]="xtls-rprx-vision"
    if pbk: q["pbk"]=pbk
    sid=p.get("sid") or s.get("reality_sid") or ""
    if sid: q["sid"]=sid
    qs="&".join(f"{k}={quote(str(v),safe='')}" for k,v in q.items() if v)
    return f"vless://{c['uuid']}@{host(s)}:{p.get('port') or s.get('vless_port','443')}?{qs}#{quote(c['email'])}"
def tg(s,chat,text):
    t=s.get("bot_token","")
    if not t or not chat: return False
    try: return requests.post(f"https://api.telegram.org/bot{t}/sendMessage",json={"chat_id":chat,"text":text},timeout=10).ok
    except Exception: return False
def allowed(c,s):
    if not c: return False,"Клиент не найден"
    if not c["enabled"]: return False,"Доступ отключён"
    if (s.get("billing_enabled")=="1" or c.get("plan_id")) and int(c["paid_until"] or 0)<=now():
        return False,"Подписка не оплачена"
    l=float(c["limit_gb"] or 0)
    if l>0 and int(c["used_bytes"] or 0)>=l*2**30: return False,"Лимит трафика исчерпан"
    return True,""
def hasplan(c): return bool(c.get("plan_id"))
def qr(text):
    try:
        import qrcode
        b=io.BytesIO(); qrcode.make(str(text)).save(b,format="PNG")
        return "data:image/png;base64,"+base64.b64encode(b.getvalue()).decode()
    except Exception: return ""
def cookie(c): return hashlib.sha256((str(c.get("access_code",""))+":"+str(c["tg_id"])).encode()).hexdigest()[:32]
def domains(raw,limit=500):
    out=[]
    for x in re.split(r"[\s,;]+",str(raw or "")[:20000]):
        x=re.sub(r"^https?://","",x.strip().lower()).split("/")[0].strip(".")
        if x and re.match(r"^[a-z0-9.-]+\.[a-z]{2,}$",x) and x not in out: out.append(x)
        if len(out)>=limit: break
    return out
def plans(only=True):
    q="SELECT * FROM plans"+(" WHERE enabled=1" if only else "")+" ORDER BY sort_order,id"
    with db() as c: return [dict(r) for r in c.execute(q)]
def plan(pid):
    try: pid=int(pid or 0)
    except Exception: return None
    if not pid: return None
    with db() as c:
        r=c.execute("SELECT * FROM plans WHERE id=?",(pid,)).fetchone(); return dict(r) if r else None
def cplan(c): return plan(c.get("plan_id"))
def promos():
    with db() as c: return [dict(r) for r in c.execute("SELECT * FROM promos ORDER BY id DESC")]
def mkpromo(code,kind,val,mx=0,exp=0,note=""):
    code=str(code or "").strip().upper()
    if not code or kind not in ("balance","plan","days"): return False,"Неверные параметры"
    with db() as c:
        if c.execute("SELECT 1 FROM promos WHERE code=?",(code,)).fetchone(): return False,"Уже есть"
        c.execute("INSERT INTO promos(code,kind,value,max_uses,expires_at,note) VALUES(?,?,?,?,?,?)",(code,kind,float(val),int(mx),int(exp),note))
    return True,f"Промокод {code} создан"
def reset(c,s,x):
    e=[]
    try: x.reset_client_traffic(ib(c,s),c["email"])
    except Exception as ex: e.append(str(ex))
    if c["http_inbound_id"]:
        try: x.reset_inbound_traffic(c["http_inbound_id"])
        except Exception as ex: e.append(str(ex))
    if e: raise RuntimeError("; ".join(e))
def sync(c,s,x):
    tot=int(float(c["limit_gb"] or 0)*2**30)
    exp=int(c["paid_until"])*1000 if (s["billing_enabled"]=="1" or c.get("plan_id")) else 0
    x.update_client(ib(c,s),c["uuid"],enable=bool(c["enabled"]),totalGB=tot,expiryTime=exp)
    if c["http_inbound_id"]:
        b=x.get_inbound(c["http_inbound_id"]); b["enable"]=bool(c["enabled"]); b["total"]=tot; b["expiryTime"]=exp
        x.update_inbound(b)
def save(c):
    with db() as con:
        con.execute("UPDATE clients SET balance=?,paid_until=?,enabled=?,notified=?,used_bytes=?,limit_gb=?,plan_id=? WHERE id=?",
          (c["balance"],c["paid_until"],c["enabled"],c["notified"],c["used_bytes"],c["limit_gb"],c.get("plan_id",0),c["id"]))
def activate(c,s,x=None,notify=True):
    c=dict(c); m=[]; p=cplan(c)
    price=float(p["price"]) if p else float(s["price"] or 0)
    period=int(p["period_days"]) if p else int(s["period_days"] or 30)
    bill=(s["billing_enabled"]=="1" or bool(p)); t=now()
    if bill and c["paid_until"]<=t:
        if c["balance"]>=price:
            c["balance"]=round(c["balance"]-price,2); c["paid_until"]=t+period*86400
            c["enabled"],c["notified"],c["used_bytes"]=1,0,0
            if p: c["limit_gb"]=float(p["limit_gb"] or 0)
            if x:
                try: reset(c,s,x)
                except Exception as e: m.append(str(e))
            u=time.strftime("%d.%m.%Y",time.localtime(c["paid_until"])); m.append(f"продлено до {u}")
            if notify: tg(s,c["tg_id"],f"✅ Продлено до {u}. Баланс: {c['balance']:.2f} ₽")
        else:
            if c["enabled"]:
                c["enabled"]=0
                if notify: tg(s,c["tg_id"],f"⛔ Подписка истекла. {cab(c,s)}")
            m.append("недостаточно средств")
    if c["enabled"] and float(c["limit_gb"] or 0)>0 and c["used_bytes"]>=float(c["limit_gb"])*2**30:
        c["enabled"]=0; m.append("лимит трафика")
    save(c)
    if x:
        try: sync(c,s,x)
        except Exception as e: m.append(f"3x-ui: {e}")
    return "; ".join(m) or "ок"
def applyplan(c,p,s,x=None,notify=True,free=False):
    c=dict(c); price=0.0 if free else float(p["price"])
    if c["balance"]<price: return False,f"Нужно {price:.2f} ₽, на балансе {c['balance']:.2f} ₽"
    c["balance"]=round(c["balance"]-price,2)
    c["paid_until"]=max(int(c["paid_until"] or 0),now())+int(p["period_days"])*86400
    c["plan_id"]=p["id"]; c["limit_gb"]=float(p["limit_gb"] or 0)
    c["enabled"],c["notified"],c["used_bytes"]=1,0,0
    save(c)
    if price>0:
        with db() as con: con.execute("INSERT INTO payments(tg_id,amount,source,status) VALUES(?,?,?,?)",(c["tg_id"],-price,"plan:"+p["name"],"paid"))
    if x:
        try: reset(c,s,x)
        except Exception: pass
        try: sync(c,s,x)
        except Exception: pass
    u=time.strftime("%d.%m.%Y",time.localtime(c["paid_until"]))
    msg=f"Тариф «{p['name']}» до {u}"+(" (бесплатно)" if free else "")
    if notify: tg(s,c["tg_id"],f"✅ {msg}\nБаланс: {c['balance']:.2f} ₽")
    return True,msg
def applypromo(c,code,s,x=None,notify=True):
    c=dict(c); code=str(code or "").strip().upper()
    if not code: return False,"Введите промокод"
    with db() as con: r=con.execute("SELECT * FROM promos WHERE code=?",(code,)).fetchone()
    if not r: return False,"Не найден"
    p=dict(r)
    if not p["enabled"]: return False,"Отключён"
    if p["expires_at"] and p["expires_at"]<now(): return False,"Истёк"
    if p["max_uses"] and p["used_count"]>=p["max_uses"]: return False,"Исчерпан"
    with db() as con:
        if con.execute("SELECT 1 FROM promo_uses WHERE promo_id=? AND client_id=?",(p["id"],c["id"])).fetchone():
            return False,"Вы уже использовали"
    k,v=p["kind"],float(p["value"] or 0)
    if k=="balance":
        with db() as con:
            con.execute("UPDATE clients SET balance=ROUND(balance+?,2) WHERE id=?",(v,c["id"]))
            con.execute("INSERT INTO payments(tg_id,amount,source,status) VALUES(?,?,?,?)",(c["tg_id"],v,"promo:"+code,"paid"))
        c["balance"]=round(c["balance"]+v,2); d=f"+{v:.2f} ₽"
    elif k=="plan":
        pl=plan(int(v))
        if not pl: return False,"Тариф не найден"
        ok,m=applyplan(c,pl,s,x,notify=False,free=True)
        if not ok: return False,m
        d=f"тариф «{pl['name']}» бесплатно"
    elif k=="days":
        u=max(int(c["paid_until"] or 0),now())+int(v)*86400
        with db() as con: con.execute("UPDATE clients SET paid_until=?,enabled=1 WHERE id=?",(u,c["id"]))
        c["paid_until"]=u; c["enabled"]=1
        if x:
            try: sync(c,s,x)
            except Exception: pass
        d=f"+{int(v)} дн."
    else: return False,"Неизвестный тип"
    with db() as con:
        con.execute("UPDATE promos SET used_count=used_count+1 WHERE id=?",(p["id"],))
        con.execute("INSERT INTO promo_uses(promo_id,client_id,detail) VALUES(?,?,?)",(p["id"],c["id"],d))
    if notify: tg(s,c["tg_id"],f"🎁 {code}: {d}")
    return True,"🎁 Применён: "+d
def sign_ok(sec,tg_id,amt,sg):
    w=hmac.new(str(sec).encode(),f"{tg_id}:{amt}".encode(),hashlib.sha256).hexdigest()
    return hmac.compare_digest(w,str(sg or ""))
def extzip(s,h):
    url=pbase(s); b=io.BytesIO()
    with zipfile.ZipFile(b,"w",zipfile.ZIP_DEFLATED) as z:
        for p in sorted((BASE/"extension").rglob("*")):
            if p.is_file(): z.writestr("pm-client/"+str(p.relative_to(BASE/"extension")),p.read_bytes().replace(b"__SERVER_URL__",url.encode()))
    return b.getvalue()
def _run(cmd,t=8):
    try:
        r=subprocess.run(cmd,shell=True,capture_output=True,text=True,timeout=t); return (r.stdout+r.stderr).strip()
    except Exception as e: return f"(err {e})"
# ---------- сертификаты ----------
def _cinfo(cert):
    out=_run(f"openssl x509 -in '{cert}' -noout -subject -issuer -enddate -ext subjectAltName 2>/dev/null",8)
    cn=iss=sub=end=""; sans=[]
    for ln in out.splitlines():
        ln=ln.strip()
        if ln.startswith("subject="):
            sub=ln.split("=",1)[1].strip(); m=re.search(r"CN\s*=\s*([^,/]+)",sub); cn=m.group(1).strip() if m else ""
        elif ln.startswith("issuer="): iss=ln.split("=",1)[1].strip()
        elif ln.startswith("notAfter="): end=ln.split("=",1)[1].strip()
        elif "DNS:" in ln or "IP Address:" in ln:
            for part in ln.split(","):
                if ":" in part: sans.append(part.split(":",1)[1].strip())
    days=None
    if end:
        try: days=int((calendar.timegm(time.strptime(end,"%b %d %H:%M:%S %Y %Z"))-time.time())/86400)
        except Exception: pass
    return {"cn":cn,"sans":sans,"end":end,"days":days,"selfsigned":bool(sub) and sub==iss}
def cert_list(s=None):
    s=s or S(); out=[]; seen=set(); paths=[]
    c=(s.get("tls_cert") or "").strip(); k=(s.get("tls_key") or "").strip()
    if c and k and os.path.isfile(c) and os.path.isfile(k): paths.append((c,k,"вручную"))
    for base in ("/root/cert","/etc/letsencrypt/live","/etc/x-ui/cert","/opt/cert","/etc/ssl/pm"):
        if os.path.isdir(base):
            try: dirs=sorted(os.listdir(base))
            except Exception: dirs=[]
            for d in dirs:
                p=os.path.join(base,d)
                if not os.path.isdir(p): continue
                for cn,kn in (("fullchain.pem","privkey.pem"),("cert.pem","key.pem"),("server.crt","server.key")):
                    cc,kk=os.path.join(p,cn),os.path.join(p,kn)
                    if os.path.isfile(cc) and os.path.isfile(kk): paths.append((cc,kk,base))
    if os.path.isfile("/etc/pm-web/self.crt"): paths.append(("/etc/pm-web/self.crt","/etc/pm-web/self.key","self-signed"))
    dom=(s.get("domain") or "").strip(); ip=server_ip(s); _,loc=ips(s)
    for cc,kk,src in paths:
        if cc in seen: continue
        seen.add(cc); i=_cinfo(cc); names=[i["cn"]]+i["sans"]
        valid=(i["days"] is None or i["days"]>0)
        out.append({"cert":cc,"key":kk,"src":src,"cn":i["cn"],"sans":i["sans"],"end":i["end"],"days":i["days"],
          "selfsigned":i["selfsigned"],"valid":valid,"trusted":(not i["selfsigned"]) and valid,
          "match":bool((dom and dom in names) or (ip and ip in names) or (loc and loc in names))})
    return out
def best_cert(s=None):
    s=s or S(); mode=(s.get("cert_mode") or "auto").lower(); lst=cert_list(s)
    if mode=="manual":
        c=(s.get("tls_cert") or "").strip(); k=(s.get("tls_key") or "").strip()
        if c and k and os.path.isfile(c) and os.path.isfile(k): return c,k
    if mode=="self":
        for x in lst:
            if x["cert"].endswith("self.crt"): return x["cert"],x["key"]
    good=[x for x in lst if x["trusted"]]
    good.sort(key=lambda x:(not x["match"],-(x["days"] or 0)))
    if good: return good[0]["cert"],good[0]["key"]
    for x in lst:
        if x["cert"].endswith("self.crt"): return x["cert"],x["key"]
    return "",""
def tlspaths(s=None): return best_cert(s)
def cert_trusted(s=None):
    s=s or S(); c,_=best_cert(s)
    if not c: return False
    for x in cert_list(s):
        if x["cert"]==c: return x["trusted"]
    return False
def tlson(s=None):
    s=s or S()
    return str(s.get("proxy_tls","1"))=="1" and cert_trusted(s)
def apply_proxy_tls(s=None):
    s=s or S(); on=tlson(s); cert,key=tlspaths(s)
    try: x=xui(s,15)
    except Exception as e: return False,f"3x-ui недоступен: {e}"
    n=0; errs=[]
    for c in clients():
        if not c.get("http_inbound_id"): continue
        try:
            b=x.get_inbound(c["http_inbound_id"]); ss=b.get("streamSettings")
            if isinstance(ss,str): ss=json.loads(ss or "{}")
            ss=dict(ss or {}); ss.pop("realitySettings",None)
            if on:
                ss["security"]="tls"
                ss["tlsSettings"]={"certificates":[{"certificateFile":cert,"keyFile":key}],"alpn":["http/1.1"],"minVersion":"1.2"}
            else: ss["security"]="none"; ss.pop("tlsSettings",None)
            b["streamSettings"]=ss; x.update_inbound(b); n+=1
        except Exception as e: errs.append(str(e)[:60])
    return True,f"{'TLS включён' if on else 'TLS снят'} на {n} прокси"+(("; "+"; ".join(errs)) if errs else "")
# ---------- доступы ----------
def apply_web_creds(s=None):
    s=s or S(); u=(s.get("web_user") or "admin").strip(); p=(s.get("web_pass") or "").strip()
    if not p: p=rnd(16); setS({"web_pass":p})
    try:
        with open("/etc/pm-web/cred","w") as f: f.write(u+"\n"+p+"\n")
        os.chmod("/etc/pm-web/cred",0o600)
    except Exception: pass
    unit=f"""[Unit]
Description=Web Terminal
After=network-online.target
[Service]
ExecStart=/usr/local/bin/ttyd -W -i 127.0.0.1 -p 7681 -c {u}:{p} /bin/bash
Restart=always
RestartSec=3
[Install]
WantedBy=multi-user.target
"""
    try:
        with open("/etc/systemd/system/web-term.service","w") as f: f.write(unit)
    except Exception: pass
    fb="/etc/pm-web/fb.db"; log=[]
    def fc(a,t=25): return _run("filebrowser "+a+" -d "+fb,t)
    def bad(r): return "error" in (r or "").lower()
    r=fc("users update '"+u+"' --password '"+p+"'")
    if bad(r):
        uid=None
        for ln in fc("users ls").splitlines():
            t=ln.split()
            if t and t[0].isdigit() and u in t: uid=t[0]; break
        if uid: r=fc("users update "+uid+" --password '"+p+"'")
        if bad(r):
            _run("systemctl stop web-files",20)
            try: os.remove(fb)
            except Exception: pass
            fc("config init"); r=fc("users add '"+u+"' '"+p+"' --perm.admin")
            log.append("база файлов пересоздана")
    log.append("filebrowser: "+("ok" if not bad(r) else (r or "")[:120]))
    old=(s.get("_fb_prev") or "").strip()
    if old and old!=u:
        for ln in fc("users ls").splitlines():
            t=ln.split()
            if t and t[0].isdigit() and old in t: fc("users rm "+t[0])
    setS({"_fb_prev":u})
    _run("systemctl daemon-reload",15)
    _run("systemctl restart web-term web-files",30)
    return True,"Доступ: "+u+" / "+p+"\n"+"\n".join(log)


def rescue_token(s=None):
    s=s or S(); t=(s.get("rescue_token") or "").strip()
    if not t:
        try: t=open("/opt/rescue-agent/token").read().strip()
        except Exception: t=""
        if not t: t=secrets.token_urlsafe(24)
        setS({"rescue_token":t})
    try:
        os.makedirs("/opt/rescue-agent",exist_ok=True)
        with open("/opt/rescue-agent/token","w") as f: f.write(t)
        os.chmod("/opt/rescue-agent/token",0o600)
    except Exception: pass
    return t
def svc(name,action):
    if name not in ("web-term","web-files","rescue-agent","proxy-admin","proxy-web","proxy-bot","proxy-monitor","nginx"): return "не разрешено"
    if action not in ("start","stop","restart"): return "не разрешено"
    return _run(f"systemctl {action} {name}",40) or "ok"
def svc_state():
    return {n:_run("systemctl is-active "+n,4) for n in
      ("web-term","web-files","rescue-agent","proxy-admin","proxy-web","proxy-bot","proxy-monitor","nginx","x-ui")}
def report():
    s=S(); c,_=tlspaths(s); p,l=ips(s)
    L=["=== PROXY MANAGER REPORT ===",time.strftime("%F %T"),
       f"domain={s.get('domain') or '(по IP)'} public_ip={p} local_ip={l} used={server_ip(s)}",
       f"cert={c or 'нет'} trusted={cert_trusted(s)} tls_proxy={tlson(s)} mode={s.get('cert_mode')}"]
    try:
        for x in cert_list(s):
            L.append("  cert %s CN=%s days=%s trusted=%s match=%s"%(x["cert"],x["cn"],x["days"],x["trusted"],x["match"]))
    except Exception as e: L.append("cert err %s"%e)
    for k,v in svc_state().items(): L.append("svc %-15s %s"%(k,v))
    for pt in (8002,8003,7681,8080,443,8443,2096,2087,2083,8444):
        try:
            with socket.create_connection(("127.0.0.1",pt),timeout=1): o="open"
        except Exception: o="closed"
        L.append("port %-5s %s"%(pt,o))
    try:
        for k,v in ibcache(s,True).items():
            if k!="_ts": L.append("inbound %s %s port=%s clients=%s enc=%s"%(k,v.get("protocol"),v.get("port"),v.get("clients"),(v.get("encryption") or "none")[:40]))
        L.append("3x-ui clients: %d"%len(xui(s,10).clients_list()))
    except Exception as e: L.append("3x-ui ERROR: %s"%e)
    try:
        with db() as con:
            L.append("DB clients=%s regs=%s plans=%s promos=%s"%(con.execute("SELECT COUNT(*) FROM clients").fetchone()[0],
              con.execute("SELECT COUNT(*) FROM registrations").fetchone()[0],con.execute("SELECT COUNT(*) FROM plans").fetchone()[0],
              con.execute("SELECT COUNT(*) FROM promos").fetchone()[0]))
            for r in con.execute("SELECT id,name,email,plan_id,paid_until,enabled,balance,http_port FROM clients LIMIT 25"):
                L.append("  #%s %s %s plan=%s paid=%s on=%s bal=%s http=%s"%tuple(r))
    except Exception as e: L.append("db err %s"%e)
    for v in ("proxy-admin","proxy-web","proxy-bot","proxy-monitor"):
        L.append("--- %s ---"%v); L.append(_run(f"journalctl -u {v} -n 12 --no-pager 2>&1|tail -12",6))
    return "\n".join(L)
