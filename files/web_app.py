import base64,json,re,time,secrets
from pathlib import Path
from urllib.parse import quote
from fastapi import FastAPI,Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse,JSONResponse,Response,PlainTextResponse
from fastapi.templating import Jinja2Templates
import common as cm
app=FastAPI(docs_url=None,redoc_url=None)
app.add_middleware(CORSMiddleware,allow_origins=["*"],allow_methods=["*"],allow_headers=["*"])
T=Jinja2Templates(directory=str(Path(__file__).parent/"templates"))
@app.on_event("startup")
def _s(): cm.init_db()
T.env.globals.update(qr=cm.qr,has_plan=cm.hasplan,get_plans=cm.plans,get_plan=cm.plan)
def used(c,s):
    try:
        x=cm.xui(s,6); u=0; st=x.get_client_stats(c["email"])
        if st: u+=int(st.get("up",0))+int(st.get("down",0))
        if c["http_inbound_id"]:
            b=x.get_inbound(c["http_inbound_id"]); u+=int(b.get("up",0))+int(b.get("down",0))
        with cm.db() as con: con.execute("UPDATE clients SET used_bytes=? WHERE id=?",(u,c["id"]))
        return u
    except Exception: return c["used_bytes"]
@app.get("/")
def index(r:Request,msg:str=""): return T.TemplateResponse(r,"landing.html",{"s":cm.S(),"msg":msg})
@app.get("/login")
def loginp(r:Request,msg:str=""): return T.TemplateResponse(r,"cabinet_login.html",{"s":cm.S(),"msg":msg})
@app.post("/login")
async def logind(r:Request):
    f=await r.form(); v=str(f.get("credential","")).strip()
    if not v: return RedirectResponse("/login?msg="+quote("Введите код или телефон"),status_code=303)
    c=cm.client(ext_key=v.upper()) or cm.client(tg_id=v)
    if not c:
        d=re.sub(r"\D","",v)
        if d:
            with cm.db() as con:
                row=con.execute("SELECT client_id FROM registrations WHERE phone=? AND status='approved' AND client_id>0 ORDER BY id DESC LIMIT 1",(d,)).fetchone()
            if row: c=cm.client(id=row["client_id"])
    if not c: return RedirectResponse("/login?msg="+quote("Клиент не найден"),status_code=303)
    return RedirectResponse("/client/"+c["tg_id"],status_code=303)
@app.post("/callback")
async def cb(r:Request):
    f=await r.form(); nm=str(f.get("name","")).strip()[:60]
    ph=re.sub(r"\D","",str(f.get("phone",""))); em=str(f.get("email","")).strip()[:100]
    cmt=str(f.get("comment","")).strip()[:400]
    if not nm or len(ph)<10: return RedirectResponse("/?msg="+quote("Укажите имя и телефон")+"#contact",status_code=303)
    code=cm.rnd(10,True)
    with cm.db() as con: con.execute("INSERT INTO registrations(name,phone,email,comment,code) VALUES(?,?,?,?,?)",(nm,ph,em,cmt,code))
    s=cm.S(); cm.tg(s,s.get("admin_tg_id"),f"📩 Заявка: {nm}, {ph}"+(f", {em}" if em else "")+(f"\n{cmt}" if cmt else ""))
    return RedirectResponse("/?msg="+quote(f"Заявка принята. Номер {code}.")+"#contact",status_code=303)
@app.get("/privacy")
def priv(r:Request): return T.TemplateResponse(r,"privacy.html",{"s":cm.S()})
@app.middleware("http")
async def guard(r:Request,nxt):
    p=r.url.path; s=cm.S()
    if p.startswith("/sub/"):
        sid=p.split("/")[2] if len(p.split("/"))>2 else ""
        c=cm.client(sub_id=sid) or cm.client(tg_id=sid)
        if not c: return PlainTextResponse("",status_code=404)
        ok,_=cm.allowed(c,s)
        if not ok: return PlainTextResponse("",status_code=403)
    if p.startswith("/client/") and not p.endswith("/unlock") and not p.endswith("/setcode"):
        tg=p.split("/")[2] if len(p.split("/"))>2 else ""
        c=cm.client(tg_id=tg)
        if c and c.get("access_code") and r.cookies.get("pm_c_"+tg)!=cm.cookie(c):
            return T.TemplateResponse(r,"lock.html",{"s":s,"c":c,"msg":r.query_params.get("msg","")})
    return await nxt(r)
@app.post("/client/{tg}/unlock")
async def ul(r:Request,tg:str):
    c=cm.client(tg_id=tg)
    if not c: return PlainTextResponse("нет",status_code=404)
    f=await r.form()
    if str(f.get("code","")).strip().upper()!=str(c.get("access_code","")).upper():
        return RedirectResponse(f"/client/{tg}?msg="+quote("Неверное кодовое слово"),status_code=303)
    x=RedirectResponse(f"/client/{tg}",status_code=303)
    x.set_cookie("pm_c_"+tg,cm.cookie(c),httponly=True,samesite="lax",path="/",max_age=30*86400); return x
@app.get("/enter/{tg}/{code}")
def ent(tg:str,code:str):
    c=cm.client(tg_id=tg)
    if not c: return PlainTextResponse("нет",status_code=404)
    if str(c.get("access_code") or "") and code.strip().upper()!=str(c["access_code"]).upper():
        return RedirectResponse(f"/client/{tg}?msg="+quote("Неверный код"),status_code=303)
    x=RedirectResponse(f"/client/{tg}",status_code=303)
    x.set_cookie("pm_c_"+tg,cm.cookie(c),httponly=True,samesite="lax",path="/",max_age=30*86400); return x
@app.get("/client/{tg}")
def cabinet(r:Request,tg:str,msg:str=""):
    c=cm.client(tg_id=tg)
    if not c: return PlainTextResponse("Клиент не найден",status_code=404)
    s=cm.S(); u=used(c,s); l=float(c["limit_gb"] or 0)
    return T.TemplateResponse(r,"client.html",{"c":c,"s":s,"msg":msg,"used_gb":cm.gb(u),
      "percent":min(100,round(u/(l*2**30)*100)) if l>0 else 0,
      "paid_str":time.strftime("%d.%m.%Y",time.localtime(c["paid_until"])) if c["paid_until"] else "—",
      "vless":cm.vless(c,s),"sub":cm.sub(c,s),"tls":cm.tlson(s)})
@app.post("/client/{tg}/setcode")
async def scode(r:Request,tg:str):
    c=cm.client(tg_id=tg)
    if not c: return PlainTextResponse("нет",status_code=404)
    f=await r.form(); n=str(f.get("new","")).strip().upper()
    if len(n)<3: return RedirectResponse(f"/client/{tg}?msg="+quote("Минимум 3 символа"),status_code=303)
    with cm.db() as con: con.execute("UPDATE clients SET access_code=? WHERE id=?",(n,c["id"]))
    c["access_code"]=n
    x=RedirectResponse(f"/client/{tg}?msg="+quote("Код изменён"),status_code=303)
    x.set_cookie("pm_c_"+tg,cm.cookie(c),httponly=True,samesite="lax",path="/",max_age=30*86400); return x
@app.post("/client/{tg}/plan/{pid}")
def cplan_(tg:str,pid:int):
    c=cm.client(tg_id=tg)
    if not c: return PlainTextResponse("нет",status_code=404)
    s=cm.S(); p=cm.plan(pid)
    if not p or not p["enabled"]: return RedirectResponse(f"/client/{tg}?msg="+quote("Тариф не найден"),status_code=303)
    ok,m=cm.applyplan(c,p,s,cm.xui(s))
    return RedirectResponse(f"/client/{tg}?msg="+quote(m),status_code=303)
@app.post("/client/{tg}/promo")
async def cpromo(r:Request,tg:str):
    c=cm.client(tg_id=tg)
    if not c: return PlainTextResponse("нет",status_code=404)
    f=await r.form(); s=cm.S(); ok,m=cm.applypromo(c,f.get("code",""),s,cm.xui(s))
    return RedirectResponse(f"/client/{tg}?msg="+quote(m),status_code=303)
@app.post("/client/{tg}/topup")
def ctop(tg:str):
    c=cm.client(tg_id=tg)
    if not c: return PlainTextResponse("нет",status_code=404)
    s=cm.S()
    with cm.db() as con: con.execute("INSERT INTO payments(tg_id,amount,source,status) VALUES(?,?,?,?)",(tg,float(s["price"] or 0),"client","pending"))
    cm.tg(s,s.get("admin_tg_id"),f"💳 {c['name']} просит пополнение")
    return RedirectResponse(f"/client/{tg}?msg="+quote("Заявка отправлена администратору"),status_code=303)
@app.get("/sub/{sid}")
def subx(sid:str):
    c=cm.client(sub_id=sid) or cm.client(tg_id=sid)
    if not c: return PlainTextResponse("",status_code=404)
    s=cm.S(); ok,_=cm.allowed(c,s)
    if not ok: return PlainTextResponse("",status_code=403)
    return PlainTextResponse(base64.b64encode(cm.vless(c,s).encode()).decode(),
      headers={"Profile-Title":base64.b64encode(s["site_name"].encode()).decode(),
        "Subscription-Userinfo":f"upload=0; download={c['used_bytes']}; total={int(float(c['limit_gb'] or 0)*2**30)}; expire={c['paid_until']}"})
def extc(key):
    c=cm.client(ext_key=str(key or "").strip().upper())
    if not c or not c["http_inbound_id"]: return None
    ok,_=cm.allowed(c,cm.S()); return c if ok else None
@app.get("/api/get_config")
def gc(key:str=""):
    c=extc(key)
    if not c: return JSONResponse({"success":False,"error":"Ключ недействителен или не оплачен"},status_code=403)
    s=cm.S()
    try: pr=json.loads(s["ext_presets"] or "{}"); ls=json.loads(s["ext_lists"] or "{}")
    except Exception: pr,ls={},{}
    return {"base_config":{"host":cm.host(s),"port":c["http_port"],"use_auth":True,
      "scheme":"https" if cm.tlson(s) else "http","username":c["http_user"],"password":c["http_pass"],"name":s["site_name"]},
      "catalog":{"presets":pr,"remote_lists":ls}}
@app.get("/api/ping")
def pg(key:str=""):
    return {"success":True} if extc(key) else JSONResponse({"success":False},status_code=403)
@app.post("/api/suggest_preset")
async def sug(r:Request):
    try: d=await r.json()
    except Exception: return JSONResponse({"success":False,"error":"Запрос"},status_code=400)
    c=extc(d.get("key"))
    if not c: return JSONResponse({"success":False,"error":"Ключ"},status_code=403)
    nm=re.sub(r"[^\wа-яА-ЯёЁ /-]","",str(d.get("name","")))[:40].strip()
    if not nm: return JSONResponse({"success":False,"error":"Название"},status_code=400)
    ds=cm.domains(d.get("domains",""))
    if not ds: return JSONResponse({"success":False,"error":"Не найдено доменов (example.com)"},status_code=400)
    with cm.db() as con: con.execute("INSERT INTO suggestions(ext_key,name,domains) VALUES(?,?,?)",(c["ext_key"],nm,",".join(ds)))
    return {"success":True}
@app.get("/extension.zip")
def ez(r:Request):
    s=cm.S(); return Response(cm.extzip(s,s.get("domain") or r.url.hostname),media_type="application/zip",
      headers={"Content-Disposition":"attachment; filename=pm-client.zip"})
@app.get("/guest/{t}")
def gu(t:str):
    s=cm.S()
    if s.get("guest_enabled")!="1" or t!=s.get("guest_token"): return PlainTextResponse("disabled",status_code=403)
    return PlainTextResponse(cm.report())
