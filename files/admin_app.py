import asyncio,json,secrets,time,os,re,subprocess,shutil,tempfile,zipfile,py_compile,socket,uuid as U
from pathlib import Path
from urllib.parse import quote
from fastapi import FastAPI,Request
from fastapi.responses import RedirectResponse,JSONResponse,Response
from fastapi.templating import Jinja2Templates
from passlib.hash import bcrypt
import common as cm
from xui_api import XUIError
app=FastAPI(docs_url=None,redoc_url=None)
T=Jinja2Templates(directory=str(Path(__file__).parent/"templates"))
SES={}; TTL=12*3600
@app.on_event("startup")
def _st():
    cm.init_db()
    try: cm.rescue_token()
    except Exception: pass
def auth(r):
    s=SES.get(r.cookies.get("pm_admin"))
    return s[0] if s and s[1]>time.time() else None
def rd(m="",to="/"): return RedirectResponse(to+("?msg="+quote(m) if m else ""),status_code=303)
def _regs():
    with cm.db() as c: return [dict(r) for r in c.execute("SELECT * FROM registrations ORDER BY id DESC LIMIT 100")]
T.env.globals.update(get_plans=cm.plans,get_plan=cm.plan,get_promos=cm.promos,get_regs=_regs,
  load_json=json.loads,server_ip=cm.server_ip,cert_ok=cm.cert_trusted,tls_on=cm.tlson)
@app.get("/login")
def lp(r:Request,msg:str=""): return T.TemplateResponse(r,"login.html",{"msg":msg})
@app.post("/login")
async def li(r:Request):
    f=await r.form(); u=str(f.get("username","")); p=str(f.get("password",""))
    with cm.db() as c: row=c.execute("SELECT * FROM admins WHERE username=?",(u,)).fetchone()
    if not row or not bcrypt.verify(p,row["password_hash"]):
        await asyncio.sleep(1); return rd("Неверный логин или пароль","/login")
    t=secrets.token_urlsafe(32); SES[t]=(u,time.time()+TTL)
    x=RedirectResponse("/",status_code=303); x.set_cookie("pm_admin",t,httponly=True,samesite="lax",max_age=TTL); return x
@app.get("/logout")
def lo(r:Request):
    SES.pop(r.cookies.get("pm_admin"),None); x=RedirectResponse("/login",status_code=303); x.delete_cookie("pm_admin"); return x
@app.get("/")
def dash(r:Request,msg:str=""):
    u=auth(r)
    if not u: return RedirectResponse("/login",status_code=303)
    s=cm.S(); cs=cm.clients()
    for c in cs:
        l=float(c["limit_gb"] or 0); c["used_gb"]=cm.gb(c["used_bytes"])
        c["percent"]=min(100,round(c["used_bytes"]/(l*2**30)*100)) if l>0 else 0
        c["paid_str"]=time.strftime("%d.%m.%Y",time.localtime(c["paid_until"])) if c["paid_until"] else "—"
    with cm.db() as con: sg=[dict(x) for x in con.execute("SELECT * FROM suggestions ORDER BY id DESC LIMIT 50")]
    return T.TemplateResponse(r,"admin.html",{"s":s,"clients":cs,"suggestions":sg,"msg":msg,"user":u})
@app.post("/settings")
async def st(r:Request):
    if not auth(r): return RedirectResponse("/login",status_code=303)
    f=await r.form(); up={}
    for k in cm.DEF:
        if k in f: up[k]=str(f[k]).strip()
    for j in ("ext_presets","ext_lists"):
        if j in up:
            try: json.loads(up[j])
            except Exception: return rd(f"{j}: невалидный JSON")
    cm.setS(up); return rd("Настройки сохранены")
def _browser(c,s,x,notes):
    used={y["http_port"] for y in cm.clients()}
    port=next((p for p in range(int(s["http_port_start"]),int(s["http_port_end"])+1) if p not in used),None)
    if port is None: notes.append("нет свободных портов"); return
    c["http_port"]=port; c["http_user"]="u"+cm.rnd(6); c["http_pass"]=secrets.token_hex(8)
    cert,key=cm.tlspaths(s) if cm.tlson(s) else ("","")
    try: c["http_inbound_id"]=x.add_http_inbound(port,c["http_user"],c["http_pass"],"browser-"+c["email"],tls_cert=cert,tls_key=key)
    except Exception as e: notes.append("HTTP: %s"%e); c["http_port"]=0; c["http_inbound_id"]=0
def _ins(c):
    with cm.db() as con:
        cur=con.execute("INSERT INTO clients(tg_id,name,email,uuid,balance,limit_gb,used_bytes,enabled,notified,paid_until,"
          "ext_key,http_port,http_user,http_pass,http_inbound_id,inbound_id,plan_id,sub_id,access_code) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
          (c["tg_id"],c["name"],c["email"],c["uuid"],c["balance"],c["limit_gb"],0,1,0,0,c["ext_key"],c["http_port"],
           c["http_user"],c["http_pass"],c["http_inbound_id"],c.get("inbound_id",0),0,cm.rnd(16),cm.rnd(6,True)))
        c["id"]=cur.lastrowid
        r=con.execute("SELECT sub_id,access_code FROM clients WHERE id=?",(c["id"],)).fetchone()
        c["sub_id"]=r["sub_id"]; c["access_code"]=r["access_code"]
@app.post("/clients/add")
async def ca(r:Request):
    if not auth(r): return RedirectResponse("/login",status_code=303)
    f=await r.form(); tg=str(f.get("tg_id","")).strip() or "u_"+cm.rnd(8)
    nm=str(f.get("name","")).strip(); em=str(f.get("email","")).strip()
    if not nm or not em: return rd("Заполните имя и email")
    if cm.client(tg_id=tg) or cm.client(email=em): return rd("tg_id или email заняты")
    s=cm.S()
    try: bal=float(f.get("balance",0) or 0); lim=float(f.get("limit_gb",0) or 0); ibid=int(f.get("inbound_id",0) or 0)
    except ValueError: return rd("Числа неверны")
    c={"tg_id":tg,"name":nm,"email":em,"uuid":str(U.uuid4()),"balance":bal,"limit_gb":lim,"used_bytes":0,
       "enabled":1,"notified":0,"paid_until":0,"ext_key":cm.rnd(8,True),"inbound_id":ibid,"plan_id":0,
       "http_port":0,"http_user":"","http_pass":"","http_inbound_id":0}
    x=cm.xui(s); notes=[]
    try: x.add_client(cm.ib(c,s),em,client_uuid=c["uuid"],total_gb=lim)
    except Exception as e: notes.append("VLESS: %s"%e)
    if f.get("browser"): _browser(c,s,x,notes)
    _ins(c); cm.activate(c,s,x)
    cm.tg(s,tg,f"👋 Доступ создан.\nКабинет: {cm.cab(c,s)}\nКод входа: {c['access_code']}\nКлюч: {c['ext_key']}")
    return rd("Клиент добавлен. "+"; ".join(notes))
@app.post("/clients/{cid}/topup")
async def tp(r:Request,cid:int):
    if not auth(r): return RedirectResponse("/login",status_code=303)
    c=cm.client(id=cid)
    if not c: return rd("Нет клиента")
    f=await r.form()
    try: a=float(f.get("amount",0) or 0)
    except ValueError: a=0
    if a<=0: return rd("Сумма > 0")
    with cm.db() as con:
        con.execute("UPDATE clients SET balance=ROUND(balance+?,2) WHERE id=?",(a,cid))
        con.execute("INSERT INTO payments(tg_id,amount,source,status) VALUES(?,?,?,?)",(c["tg_id"],a,"admin","paid"))
    c=cm.client(id=cid); s=cm.S(); res=cm.activate(c,s,cm.xui(s))
    cm.tg(s,c["tg_id"],f"💰 +{a:.2f} ₽"); return rd("Пополнено. "+res)
@app.post("/clients/{cid}/reset")
def rs(r:Request,cid:int):
    if not auth(r): return RedirectResponse("/login",status_code=303)
    c=cm.client(id=cid)
    if not c: return rd("Нет клиента")
    s=cm.S(); x=cm.xui(s); n=[]
    try: cm.reset(c,s,x)
    except Exception as e: n.append(str(e))
    c["used_bytes"]=0; c["notified"]=0
    return rd("Сброшен. "+cm.activate(c,s,x)+"; ".join(n))
@app.post("/clients/{cid}/toggle")
def tgl(r:Request,cid:int):
    if not auth(r): return RedirectResponse("/login",status_code=303)
    c=cm.client(id=cid)
    if not c: return rd("Нет клиента")
    c["enabled"]=0 if c["enabled"] else 1
    with cm.db() as con: con.execute("UPDATE clients SET enabled=? WHERE id=?",(c["enabled"],cid))
    s=cm.S(); n=""
    try: cm.sync(c,s,cm.xui(s))
    except Exception as e: n=" (%s)"%e
    return rd(("Включён" if c["enabled"] else "Отключён")+n)
@app.post("/clients/{cid}/sync")
def sy(r:Request,cid:int):
    if not auth(r): return RedirectResponse("/login",status_code=303)
    c=cm.client(id=cid)
    if not c: return rd("Нет клиента")
    s=cm.S(); x=cm.xui(s)
    try: cm.sync(c,s,x)
    except XUIError:
        try:
            x.add_client(cm.ib(c,s),c["email"],client_uuid=c["uuid"],total_gb=c["limit_gb"]); cm.sync(c,s,x)
        except Exception as e: return rd("Ошибка: %s"%e)
    except Exception as e: return rd("Ошибка: %s"%e)
    return rd("Синхронизировано")
@app.post("/clients/{cid}/delete")
def dl(r:Request,cid:int):
    if not auth(r): return RedirectResponse("/login",status_code=303)
    c=cm.client(id=cid)
    if not c: return rd("Нет клиента")
    s=cm.S(); x=cm.xui(s); n=[]
    try: x.del_client(cm.ib(c,s),c["uuid"])
    except Exception as e: n.append(str(e))
    if c["http_inbound_id"]:
        try: x.del_inbound(c["http_inbound_id"])
        except Exception as e: n.append(str(e))
    with cm.db() as con: con.execute("DELETE FROM clients WHERE id=?",(cid,))
    return rd("Удалён. "+"; ".join(n))
@app.post("/clients/{cid}/browser")
def br(r:Request,cid:int):
    if not auth(r): return RedirectResponse("/login",status_code=303)
    c=cm.client(id=cid)
    if not c: return rd("Нет клиента")
    if c["http_inbound_id"]: return rd("Уже есть")
    s=cm.S(); n=[]; _browser(c,s,cm.xui(s),n)
    with cm.db() as con:
        con.execute("UPDATE clients SET http_port=?,http_user=?,http_pass=?,http_inbound_id=? WHERE id=?",
          (c["http_port"],c["http_user"],c["http_pass"],c["http_inbound_id"],cid))
    return rd("Прокси порт %s. %s"%(c["http_port"],"; ".join(n)))
@app.post("/clients/{cid}/code")
async def cd(r:Request,cid:int):
    if not auth(r): return RedirectResponse("/login",status_code=303)
    f=await r.form(); v=str(f.get("code","")).strip().upper() or cm.rnd(6,True)
    with cm.db() as con: con.execute("UPDATE clients SET access_code=? WHERE id=?",(v,cid))
    return rd("Код: "+v)
@app.post("/clients/{cid}/codeoff")
def co(r:Request,cid:int):
    if not auth(r): return RedirectResponse("/login",status_code=303)
    with cm.db() as con: con.execute("UPDATE clients SET access_code='' WHERE id=?",(cid,))
    return rd("Защита кабинета отключена")
@app.post("/clients/{cid}/setplan/{pid}")
def sp(r:Request,cid:int,pid:int):
    if not auth(r): return RedirectResponse("/login",status_code=303)
    c=cm.client(id=cid); p=cm.plan(pid)
    if not c or not p: return rd("Нет клиента/тарифа")
    s=cm.S(); ok,m=cm.applyplan(c,p,s,cm.xui(s),free=True); return rd(m)
@app.post("/security")
async def sec(r:Request):
    u=auth(r)
    if not u: return RedirectResponse("/login",status_code=303)
    f=await r.form(); o,n,n2=str(f.get("old","")),str(f.get("new","")),str(f.get("new2",""))
    with cm.db() as con: row=con.execute("SELECT * FROM admins WHERE username=?",(u,)).fetchone()
    if not row or not bcrypt.verify(o,row["password_hash"]): return RedirectResponse("/access?msg="+quote("Старый пароль неверен"),status_code=303)
    if len(n)<6 or n!=n2: return RedirectResponse("/access?msg="+quote("Минимум 6 символов, поля должны совпадать"),status_code=303)
    with cm.db() as con: con.execute("UPDATE admins SET password_hash=? WHERE username=?",(bcrypt.hash(n),u))
    SES.clear(); return RedirectResponse("/login?msg="+quote("Пароль изменён"),status_code=303)
@app.get("/api/xui_status")
def xs(r:Request):
    if not auth(r): return JSONResponse({"ok":False},status_code=401)
    try:
        st=cm.xui(cm.S(),6).status() or {}; x=st.get("xray") or {}
        return {"ok":True,"xray":x.get("state","?"),"cpu":round(float(st.get("cpu",0)),1)}
    except Exception as e: return {"ok":False,"error":str(e)}
@app.get("/xui/inbounds")
def xi(r:Request):
    if not auth(r): return JSONResponse({"ok":False},status_code=401)
    try:
        ca=cm.ibcache(cm.S(),True)
        return {"ok":True,"inbounds":[dict(v,id=k) for k,v in ca.items() if k!="_ts" and v.get("protocol")=="vless"]}
    except Exception as e: return {"ok":False,"error":str(e)}
@app.post("/xui/autoconfig")
async def ac(r:Request):
    if not auth(r): return RedirectResponse("/login",status_code=303)
    f=await r.form(); s=cm.S()
    try: ibs=cm.xui(s,10).get_inbounds()
    except Exception as e: return rd("3x-ui недоступен: %s"%e)
    vl=[b for b in ibs if b.get("protocol")=="vless"]
    if not vl: return rd("Нет VLESS inbound")
    cm.ibcache(s,True); pick=str(f.get("inbound_id","")).strip()
    ch=next((b for b in vl if str(b.get("id"))==pick),None) if pick else None
    if ch is None:
        def ncl(b):
            st=b.get("settings")
            if isinstance(st,str):
                try: st=json.loads(st)
                except Exception: st={}
            return len((st or {}).get("clients") or [])
        ch=max(vl,key=ncl)
    p=cm.ibcache(s).get(str(ch["id"])) or {}
    up={"inbound_id":str(ch["id"]),"vless_port":str(p.get("port") or ch.get("port"))}
    for k,v in (("sni",p.get("sni")),("reality_pbk",p.get("pbk")),("reality_sid",p.get("sid")),("fp",p.get("fp"))):
        if v: up[k]=v
    cm.setS(up); return rd(f"Inbound №{ch['id']}, порт {up['vless_port']}, SNI {up.get('sni','—')}")
@app.post("/clients/import")
async def im(r:Request):
    if not auth(r): return RedirectResponse("/login",status_code=303)
    f=await r.form(); s=cm.S()
    try: src=int(f.get("inbound_id",0) or 0) or int(s["inbound_id"])
    except ValueError: src=int(s["inbound_id"])
    try: cl=cm.xui(s,15).clients_list()
    except Exception as e: return rd("Ошибка: %s"%e)
    add=skip=0
    for c in cl:
        em=str(c.get("email") or "").strip(); cu=str(c.get("uuid") or c.get("id") or "")
        if not em or cm.client(email=em) or (cu and cm.client(uuid=cu)): skip+=1; continue
        tot=int(c.get("totalGB") or 0); exp=int(c.get("expiryTime") or 0)
        t=c.get("traffic") or {}; us=int(t.get("up") or 0)+int(t.get("down") or 0) if isinstance(t,dict) else 0
        tg=str(c.get("tgId") or "").strip()
        if not tg or tg=="0" or cm.client(tg_id=tg): tg="imp_"+cm.rnd(8)
        with cm.db() as con:
            con.execute("INSERT INTO clients(tg_id,name,email,uuid,balance,limit_gb,used_bytes,enabled,notified,paid_until,ext_key,inbound_id,sub_id,access_code) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
              (tg,em,em,cu or str(U.uuid4()),0,round(tot/2**30,2) if tot else 0,us,1 if c.get("enable",True) else 0,0,
               exp//1000 if exp>0 else 0,cm.rnd(8,True),src,cm.rnd(16),cm.rnd(6,True)))
        add+=1
    return rd(f"Импорт №{src}: +{add}, пропущено {skip}")
@app.post("/registrations/{rid}/approve")
async def ra(r:Request,rid:int):
    if not auth(r): return RedirectResponse("/login",status_code=303)
    f=await r.form()
    with cm.db() as con: row=con.execute("SELECT * FROM registrations WHERE id=?",(rid,)).fetchone()
    if not row: return rd("Не найдена")
    if row["status"]!="pending": return rd("Обработана")
    g=dict(row); s=cm.S()
    try:
        bal=float(f.get("balance",0) or 0); lim=float(f.get("limit_gb",0) or 0)
        ibid=int(f.get("inbound_id",0) or 0); pid=int(f.get("plan_id",0) or 0)
    except ValueError: bal=lim=ibid=pid=0
    p=cm.plan(pid)
    if p: lim=float(p["limit_gb"] or 0)
    dg=re.sub(r"\D","",g["phone"]); em="u"+(dg or cm.rnd(6))
    while cm.client(email=em): em="u"+cm.rnd(6)
    tg=g["tg_id"] or "u_"+cm.rnd(8)
    if cm.client(tg_id=tg): tg="u_"+cm.rnd(8)
    c={"tg_id":tg,"name":g["name"],"email":em,"uuid":str(U.uuid4()),"balance":bal,"limit_gb":lim,"used_bytes":0,
       "enabled":1,"notified":0,"paid_until":0,"ext_key":cm.rnd(8,True),"inbound_id":ibid,"plan_id":0,
       "http_port":0,"http_user":"","http_pass":"","http_inbound_id":0}
    x=cm.xui(s); n=[]
    try: x.add_client(cm.ib(c,s),em,client_uuid=c["uuid"],total_gb=lim)
    except Exception as e: n.append("VLESS: %s"%e)
    if f.get("browser"): _browser(c,s,x,n)
    _ins(c)
    with cm.db() as con: con.execute("UPDATE registrations SET status='approved',client_id=?,decided_at=datetime('now') WHERE id=?",(c["id"],rid))
    if p: cm.applyplan(c,p,s,x,notify=False,free=True); c=cm.client(id=c["id"])
    else: cm.activate(c,s,x)
    if g["tg_id"]: cm.tg(s,g["tg_id"],f"✅ Одобрено!\n{cm.cab(c,s)}\nКод: {c['access_code']}\nКлюч: {c['ext_key']}")
    return rd("Одобрено: "+c["email"]+"; ".join(n))
@app.post("/registrations/{rid}/reject")
def rj(r:Request,rid:int):
    if not auth(r): return RedirectResponse("/login",status_code=303)
    with cm.db() as con:
        row=con.execute("SELECT * FROM registrations WHERE id=?",(rid,)).fetchone()
        if row and row["status"]=="pending": con.execute("UPDATE registrations SET status='rejected',decided_at=datetime('now') WHERE id=?",(rid,))
    if row and row["tg_id"]: cm.tg(cm.S(),row["tg_id"],"❌ Отклонена")
    return rd("Отклонена")
@app.post("/registrations/{rid}/delete")
def rdel(r:Request,rid:int):
    if not auth(r): return RedirectResponse("/login",status_code=303)
    with cm.db() as con: con.execute("DELETE FROM registrations WHERE id=?",(rid,))
    return rd("Удалена")
@app.post("/registrations/clear")
def rcl(r:Request):
    if not auth(r): return RedirectResponse("/login",status_code=303)
    with cm.db() as con: n=con.execute("DELETE FROM registrations WHERE status!='pending'").rowcount
    return rd("Удалено: %s"%n)
@app.post("/plans/add")
async def pa(r:Request):
    if not auth(r): return RedirectResponse("/login",status_code=303)
    f=await r.form(); nm=str(f.get("name","")).strip()
    if not nm: return rd("Название обязательно")
    try: pr=float(f.get("price",0) or 0); dy=int(f.get("period_days",30) or 30); lm=float(f.get("limit_gb",0) or 0)
    except ValueError: return rd("Числа неверны")
    with cm.db() as con: con.execute("INSERT INTO plans(name,price,period_days,limit_gb,description,sort_order) VALUES(?,?,?,?,?,?)",(nm,pr,dy,lm,str(f.get("description","")).strip(),100))
    return rd("Тариф добавлен")
@app.post("/plans/{pid}/save")
async def psv(r:Request,pid:int):
    if not auth(r): return RedirectResponse("/login",status_code=303)
    f=await r.form()
    try: pr=float(f.get("price",0) or 0); dy=int(f.get("period_days",30) or 30); lm=float(f.get("limit_gb",0) or 0)
    except ValueError: return rd("Числа неверны")
    with cm.db() as con: con.execute("UPDATE plans SET name=?,price=?,period_days=?,limit_gb=?,description=? WHERE id=?",(str(f.get("name","")).strip(),pr,dy,lm,str(f.get("description","")).strip(),pid))
    return rd("Сохранено")
@app.post("/plans/{pid}/toggle")
def pt(r:Request,pid:int):
    if not auth(r): return RedirectResponse("/login",status_code=303)
    with cm.db() as con: con.execute("UPDATE plans SET enabled=1-enabled WHERE id=?",(pid,))
    return rd("Переключено")
@app.post("/plans/{pid}/delete")
def pd(r:Request,pid:int):
    if not auth(r): return RedirectResponse("/login",status_code=303)
    with cm.db() as con:
        con.execute("DELETE FROM plans WHERE id=?",(pid,)); con.execute("UPDATE clients SET plan_id=0 WHERE plan_id=?",(pid,))
    return rd("Удалён")
@app.post("/promos/add")
async def pra(r:Request):
    if not auth(r): return RedirectResponse("/login",status_code=303)
    f=await r.form()
    try: v=float(f.get("value",0) or 0); mx=int(f.get("max_uses",0) or 0); vd=int(f.get("valid_days",0) or 0)
    except ValueError: return rd("Числа неверны")
    ok,m=cm.mkpromo(f.get("code",""),str(f.get("kind","balance")),v,mx,cm.now()+vd*86400 if vd>0 else 0,"")
    return rd(m)
@app.post("/promos/{pid}/toggle")
def prt(r:Request,pid:int):
    if not auth(r): return RedirectResponse("/login",status_code=303)
    with cm.db() as con: con.execute("UPDATE promos SET enabled=1-enabled WHERE id=?",(pid,))
    return rd("Переключено")
@app.post("/promos/{pid}/delete")
def prd(r:Request,pid:int):
    if not auth(r): return RedirectResponse("/login",status_code=303)
    with cm.db() as con: con.execute("DELETE FROM promos WHERE id=?",(pid,))
    return rd("Удалён")
@app.post("/presets/add")
async def psa(r:Request):
    if not auth(r): return RedirectResponse("/login",status_code=303)
    f=await r.form(); nm=str(f.get("name","")).strip()[:40]; ds=cm.domains(f.get("domains",""))
    if not nm or not ds: return rd("Нужны название и домены")
    s=cm.S()
    try: pr=json.loads(s["ext_presets"] or "{}")
    except Exception: pr={}
    pr[nm]=sorted(set(pr.get(nm,[])+ds)); cm.setS({"ext_presets":json.dumps(pr,ensure_ascii=False)})
    return rd(f"«{nm}»: {len(pr[nm])} доменов")
@app.post("/presets/delete")
async def psd(r:Request):
    if not auth(r): return RedirectResponse("/login",status_code=303)
    f=await r.form(); s=cm.S()
    try: pr=json.loads(s["ext_presets"] or "{}")
    except Exception: pr={}
    pr.pop(str(f.get("name","")),None); cm.setS({"ext_presets":json.dumps(pr,ensure_ascii=False)}); return rd("Удалён")
@app.post("/suggestions/{sid}/approve")
def sga(r:Request,sid:int):
    if not auth(r): return RedirectResponse("/login",status_code=303)
    s=cm.S()
    with cm.db() as con:
        row=con.execute("SELECT * FROM suggestions WHERE id=?",(sid,)).fetchone()
        if row:
            pr=json.loads(s["ext_presets"] or "{}"); ds=[d.strip() for d in (row["domains"] or "").split(",") if d.strip()]
            pr[row["name"]]=sorted(set(pr.get(row["name"],[])+ds)); cm.setS({"ext_presets":json.dumps(pr,ensure_ascii=False)})
            con.execute("DELETE FROM suggestions WHERE id=?",(sid,))
    return rd("Обновлён")
@app.post("/suggestions/{sid}/delete")
def sgd(r:Request,sid:int):
    if not auth(r): return RedirectResponse("/login",status_code=303)
    with cm.db() as con: con.execute("DELETE FROM suggestions WHERE id=?",(sid,))
    return rd("Удалено")
@app.post("/webhook/payment")
async def wh(r:Request):
    try: d=await r.json()
    except Exception: return JSONResponse({"ok":False},status_code=400)
    s=cm.S(); tg=str(d.get("tg_id","")); a=d.get("amount",0)
    if not cm.sign_ok(s["billing_secret"],tg,a,d.get("sign","")): return JSONResponse({"ok":False,"error":"sign"},status_code=403)
    try: a=float(a)
    except Exception: return JSONResponse({"ok":False},status_code=400)
    c=cm.client(tg_id=tg)
    if not c or a<=0: return JSONResponse({"ok":False},status_code=400)
    eid=str(d.get("payment_id",""))
    with cm.db() as con:
        if eid and con.execute("SELECT 1 FROM payments WHERE external_id=? AND source='webhook'",(eid,)).fetchone():
            return {"ok":True,"duplicate":True}
        con.execute("UPDATE clients SET balance=ROUND(balance+?,2) WHERE id=?",(a,c["id"]))
        con.execute("INSERT INTO payments(tg_id,amount,source,status,external_id) VALUES(?,?,?,?,?)",(tg,a,"webhook","paid",eid))
    c=cm.client(tg_id=tg); cm.activate(c,s,cm.xui(s)); cm.tg(s,tg,f"💰 {a:.2f} ₽")
    return {"ok":True,"balance":c["balance"]}
@app.post("/guest/toggle")
def gt(r:Request):
    if not auth(r): return RedirectResponse("/login",status_code=303)
    s=cm.S(); cm.setS({"guest_enabled":"0" if s.get("guest_enabled")=="1" else "1"})
    return RedirectResponse("/access?msg="+quote("Гостевой доступ переключён"),status_code=303)
@app.post("/guest/rotate")
def gr(r:Request):
    if not auth(r): return RedirectResponse("/login",status_code=303)
    cm.setS({"guest_token":secrets.token_urlsafe(24),"guest_enabled":"0"})
    return RedirectResponse("/access?msg="+quote("Токен обновлён"),status_code=303)
@app.get("/api/diagnostics")
def dg(r:Request):
    if not auth(r): return JSONResponse({"ok":False},status_code=401)
    return {"ok":True,"report":cm.report()}
@app.get("/api/probe")
def pb(r:Request):
    if not auth(r): return JSONResponse({"ok":False},status_code=401)
    try: return {"ok":True,"routes":cm.xui(cm.S(),10).probe()}
    except Exception as e: return {"ok":False,"error":str(e)}
RES="/opt/proxy-manager/update_result.txt"
@app.post("/update/upload")
async def uu(r:Request):
    if not auth(r): return RedirectResponse("/login",status_code=303)
    f=await r.form(); up=f.get("file")
    if up is None or not getattr(up,"filename",""): return rd("Файл не выбран")
    data=await up.read(); nm=up.filename; tmp=tempfile.mkdtemp(prefix="pmu_"); files={}
    try:
        if nm.endswith(".zip"):
            zp=os.path.join(tmp,"u.zip"); open(zp,"wb").write(data)
            with zipfile.ZipFile(zp) as z:
                for n in z.namelist():
                    if n.endswith("/") or ".." in n or n.startswith("/"): continue
                    files[n]=z.read(n)
        else: files[nm]=data
        if not files: return rd("Пусто")
        errs=[]
        for n,b in files.items():
            tp=os.path.join(tmp,"chk_"+n.replace("/","_")); open(tp,"wb").write(b)
            if n.endswith(".py"):
                try: py_compile.compile(tp,doraise=True)
                except Exception as e: errs.append(f"{n}: {e}")
            if n.endswith(".html"):
                try:
                    from jinja2 import Environment
                    Environment().parse(b.decode("utf-8","replace"))
                except Exception as e: errs.append(f"{n}: {e}")
        if errs:
            open(RES,"w").write("ОШИБКА:\n"+"\n".join(errs)); return rd("Отклонено: "+"; ".join(errs)[:300])
        bd="/opt/proxy-manager/backups/"+time.strftime("%Y%m%d_%H%M%S"); os.makedirs(bd,exist_ok=True)
        for n in files:
            d0=os.path.join("/opt/proxy-manager",n)
            if os.path.exists(d0):
                bp=os.path.join(bd,n); os.makedirs(os.path.dirname(bp),exist_ok=True); shutil.copy2(d0,bp)
        for n,b in files.items():
            d0=os.path.join("/opt/proxy-manager",n); os.makedirs(os.path.dirname(d0),exist_ok=True); open(d0,"wb").write(b)
        open(RES,"w").write("ПРИМЕНЯЕТСЯ…")
        sc=("sleep 1; systemctl restart proxy-admin proxy-web proxy-bot proxy-monitor; sleep 6; "
            "A=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8003/login); "
            "B=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8002/); "
            f"if [ \"$A\" = 200 ] && [ \"$B\" = 200 ]; then echo УСПЕХ > {RES}; "
            f"else cp -rf {bd}/* /opt/proxy-manager/ 2>/dev/null; systemctl restart proxy-admin proxy-web proxy-bot proxy-monitor; "
            f"{{ echo \"ОШИБКА admin=$A web=$B — откат\"; journalctl -u proxy-admin -n 25 --no-pager; }} > {RES}; fi")
        subprocess.Popen(["bash","-c",sc],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        return rd("Применено. «Статус» через 10 сек")
    except Exception as e:
        open(RES,"w").write("ОШИБКА: %s"%e); return rd("Ошибка: %s"%e)
@app.get("/update/status")
def us(r:Request):
    if not auth(r): return JSONResponse({"ok":False},status_code=401)
    try: return {"ok":True,"text":open(RES).read()}
    except Exception: return {"ok":True,"text":"Обновлений не было"}
@app.get("/extension.zip")
def ez(r:Request):
    if not auth(r): return RedirectResponse("/login",status_code=303)
    s=cm.S(); return Response(cm.extzip(s,s.get("domain") or r.url.hostname),media_type="application/zip",
      headers={"Content-Disposition":"attachment; filename=pm-client.zip"})
NETLOG="/opt/proxy-manager/net_result.txt"; CERTLOG="/opt/proxy-manager/cert_result.txt"
@app.get("/certs")
def cp_(r:Request,msg:str=""):
    if not auth(r): return RedirectResponse("/login",status_code=303)
    s=cm.S(); pub,loc=cm.ips(s)
    return T.TemplateResponse(r,"certs.html",{"s":s,"msg":msg,"certs":cm.cert_list(s),
      "chosen":cm.tlspaths(s)[0],"trusted":cm.cert_trusted(s),"tlson":cm.tlson(s),
      "ip":cm.server_ip(s),"pub":pub,"loc":loc})
@app.post("/certs/apply")
async def ca_(r:Request):
    if not auth(r): return RedirectResponse("/login",status_code=303)
    f=await r.form()
    dom=re.sub(r"^https?://","",str(f.get("domain","")).strip().lower()).split("/")[0]
    cm.setS({"cert_mode":str(f.get("cert_mode","auto")),"domain":dom,
      "server_ip":str(f.get("server_ip","")).strip(),
      "tls_cert":str(f.get("tls_cert","")).strip(),"tls_key":str(f.get("tls_key","")).strip(),
      "le_email":str(f.get("le_email","")).strip(),"proxy_tls":str(f.get("proxy_tls","1"))})
    open(NETLOG,"w").write("ПРИМЕНЯЕТСЯ…")
    subprocess.Popen(["bash","-c",f"bash {cm.BASE}/net-setup.sh > {NETLOG} 2>&1"],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    return RedirectResponse("/certs?msg="+quote("Применяю везде. Обнови через 10 сек."),status_code=303)
@app.post("/certs/le")
async def cl_(r:Request):
    if not auth(r): return RedirectResponse("/login",status_code=303)
    s=cm.S(); d=(s.get("domain") or "").strip()
    if not d: return RedirectResponse("/certs?msg="+quote("Сначала укажи домен и «Применить везде»"),status_code=303)
    ip=cm.server_ip(s)
    try: dip=socket.gethostbyname(d)
    except Exception: dip=None
    warn="" if dip==ip else f"\nВНИМАНИЕ: {d} -> {dip}, IP сервера {ip}\n"
    em=(s.get("le_email") or "").strip(); mail=f"-m {em}" if em else "--register-unsafely-without-email"
    open(CERTLOG,"w").write("ЗАПРОС…"+warn)
    sc=(f"{{ certbot certonly --webroot -w /var/www/certbot -d {d} --non-interactive --agree-tos {mail} "
        f"--deploy-hook 'systemctl reload nginx' 2>&1; "
        f"if [ -f /etc/letsencrypt/live/{d}/fullchain.pem ]; then echo ПОЛУЧЕН; bash {cm.BASE}/net-setup.sh 2>&1; "
        f"else echo 'НЕ УДАЛОСЬ: домен должен указывать на {ip}, порт 80 открыт'; fi; }} > {CERTLOG} 2>&1")
    subprocess.Popen(["bash","-c",sc],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    return RedirectResponse("/certs?msg="+quote("Запущено, обнови через 20-30 сек."+warn),status_code=303)
@app.post("/certs/proxy")
def cpx(r:Request):
    if not auth(r): return RedirectResponse("/login",status_code=303)
    return RedirectResponse("/certs?msg="+quote(cm.apply_proxy_tls()[1]),status_code=303)
@app.get("/certs/status")
def cs_(r:Request):
    if not auth(r): return JSONResponse({"ok":False},status_code=401)
    t=""
    for p in (NETLOG,CERTLOG):
        try: t+="\n--- "+p+" ---\n"+open(p).read()
        except Exception: pass
    return {"ok":True,"text":t or "Ничего не запускали"}
@app.get("/access")
def acc(r:Request,msg:str=""):
    if not auth(r): return RedirectResponse("/login",status_code=303)
    s=cm.S(); tok=cm.rescue_token(s); s=cm.S()
    return T.TemplateResponse(r,"access.html",{"s":s,"msg":msg,"tok":tok,"st":cm.svc_state(),
      "base":cm.pbase(s),"ip":cm.server_ip(s)})
@app.post("/access/creds")
async def accc(r:Request):
    if not auth(r): return RedirectResponse("/login",status_code=303)
    f=await r.form()
    u=str(f.get("web_user","admin")).strip() or "admin"
    p=str(f.get("web_pass","")).strip()
    if str(f.get("gen"))=="1" or not p: p=cm.rnd(16)
    if len(p)<6: return RedirectResponse("/access?msg="+quote("Пароль минимум 6 символов"),status_code=303)
    cm.setS({"web_user":u,"web_pass":p}); ok,m=cm.apply_web_creds()
    return RedirectResponse("/access?msg="+quote(m),status_code=303)
@app.post("/access/svc/{name}/{action}")
def accs(r:Request,name:str,action:str):
    if not auth(r): return RedirectResponse("/login",status_code=303)
    res=cm.svc(name,action)
    return RedirectResponse("/access?msg="+quote(f"{name} {action}: {res}"),status_code=303)
@app.post("/access/rescue")
def accr(r:Request):
    if not auth(r): return RedirectResponse("/login",status_code=303)
    cm.setS({"rescue_token":secrets.token_urlsafe(24)}); cm.rescue_token(); cm.svc("rescue-agent","restart")
    return RedirectResponse("/access?msg="+quote("Токен резервного канала обновлён"),status_code=303)
@app.get("/site")
def site(r:Request,msg:str=""):
    if not auth(r): return RedirectResponse("/login",status_code=303)
    return T.TemplateResponse(r,"site.html",{"s":cm.S(),"msg":msg})
@app.post("/site")
async def sites(r:Request):
    if not auth(r): return RedirectResponse("/login",status_code=303)
    f=await r.form(); up={}
    for k in ("site_name","site_tagline","site_about","site_phone","site_email","site_inn","site_addr",
              "site_years","site_projects","site_uptime"):
        if k in f: up[k]=str(f[k]).strip()
    cm.setS(up); return RedirectResponse("/site?msg="+quote("Сохранено"),status_code=303)


# ================= GITHUB =================
import gitops as go
@app.get("/git")
def git_page(r:Request,msg:str=""):
    if not auth(r): return RedirectResponse("/login",status_code=303)
    s=cm.S()
    return T.TemplateResponse(r,"git.html",{"s":s,"msg":msg,"cfg":go.cfg()})
@app.post("/git/save")
async def git_save(r:Request):
    if not auth(r): return RedirectResponse("/login",status_code=303)
    f=await r.form()
    cm.setS({"git_repo":str(f.get("repo","")).strip(),"git_branch":str(f.get("branch","main")).strip() or "main",
             "git_token":str(f.get("token","")).strip()})
    return RedirectResponse("/git?msg="+quote("Сохранено"),status_code=303)
def _bg(fn):
    open(go.LOG,"w").write("ВЫПОЛНЯЕТСЯ…")
    code="import gitops,traceback\ntry:\n ok,out=gitops.%s\n open(gitops.LOG,'w').write(('OK\\n' if ok else 'FAIL\\n')+out)\nexcept Exception:\n open(gitops.LOG,'w').write('ERROR\\n'+traceback.format_exc())"%fn
    subprocess.Popen(["bash","-c",f"cd {cm.BASE} && ./venv/bin/python -c \"{code}\""],
                     stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
@app.post("/git/check")
def git_check(r:Request):
    if not auth(r): return RedirectResponse("/login",status_code=303)
    open(go.LOG,"w").write("ПРОВЕРКА…")
    code="import gitops,traceback\ntry:\n open(gitops.LOG,'w').write(gitops.check())\nexcept Exception:\n open(gitops.LOG,'w').write(traceback.format_exc())"
    subprocess.Popen(["bash","-c",f"cd {cm.BASE} && ./venv/bin/python -c \"{code}\""],
                     stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    return RedirectResponse("/git?msg="+quote("Проверяю репозиторий. «Статус» через 10 сек."),status_code=303)
@app.post("/git/update")
def git_update(r:Request):
    if not auth(r): return RedirectResponse("/login",status_code=303)
    _bg("update(False)")
    return RedirectResponse("/git?msg="+quote("Обновление запущено. «Статус» через 20-30 сек."),status_code=303)
@app.post("/git/reinstall")
def git_reinst(r:Request):
    if not auth(r): return RedirectResponse("/login",status_code=303)
    c=go.cfg()
    if not c["repo"]: return RedirectResponse("/git?msg="+quote("Укажи репозиторий"),status_code=303)
    u=go._url(c); br=c["branch"]
    sc=(f"rm -rf /tmp/pmre && git clone --depth 1 -b {br} '{u}' /tmp/pmre > {go.LOG} 2>&1 && "
        f"DOMAIN=$(cd {cm.BASE} && ./venv/bin/python -c 'import common;print(common.S().get(\"domain\") or \"\")') "
        f"bash /tmp/pmre/install.sh >> {go.LOG} 2>&1")
    subprocess.Popen(["bash","-c",sc],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    return RedirectResponse("/git?msg="+quote("Полная переустановка из репо запущена. Следи за «Статус»."),status_code=303)
@app.get("/git/status")
def git_status(r:Request):
    if not auth(r): return JSONResponse({"ok":False},status_code=401)
    try: return {"ok":True,"text":open(go.LOG).read()}
    except Exception: return {"ok":True,"text":"Операций ещё не было"}
@app.get("/git/export")
def git_export(r:Request):
    if not auth(r): return RedirectResponse("/login",status_code=303)
    return Response(go.export_zip(),media_type="application/zip",
      headers={"Content-Disposition":"attachment; filename=proxy-manager-github.zip"})
@app.get("/git/installer")
def git_inst(r:Request):
    if not auth(r): return RedirectResponse("/login",status_code=303)
    return Response(go.build_installer(),media_type="text/x-shellscript",
      headers={"Content-Disposition":"attachment; filename=install.sh"})
