import asyncio,logging,time
from aiogram import Bot,Dispatcher,Router,F
from aiogram.filters import Command,CommandStart
from aiogram.types import Message,CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
import common as cm
logging.basicConfig(level=logging.INFO,format="%(asctime)s %(levelname)s %(message)s")
log=logging.getLogger("bot"); R=Router()
def S(): return cm.S()
def adm(u): return str(u)==str(S().get("admin_tg_id","")).strip()
def me(u): return cm.client(tg_id=str(u))
def kb():
    b=InlineKeyboardBuilder()
    for t,c in (("📊 Кабинет","me"),("💰 Тарифы","plans"),("🎁 Промокод","promo"),("🔑 Ключ","key")): b.button(text=t,callback_data=c)
    b.adjust(1); return b.as_markup()
def pkb():
    b=InlineKeyboardBuilder()
    for p in cm.plans():
        l=("%g ГБ"%p["limit_gb"]) if p["limit_gb"] else "безлимит"
        b.button(text=f"{p['name']} · {p['price']:g}₽/{p['period_days']}д · {l}",callback_data="buy:%d"%p["id"])
    b.button(text="⬅️ Меню",callback_data="menu"); b.adjust(1); return b.as_markup()
def mtext(c,s):
    p=cm.cplan(c); l=("%g ГБ"%c["limit_gb"]) if c["limit_gb"] else "∞"
    u=time.strftime("%d.%m.%Y",time.localtime(c["paid_until"])) if c["paid_until"] else "—"
    return (f"📊 {c['name']}\n\n{'🟢 активен' if c['enabled'] else '🔴 отключён'}\nБаланс: {c['balance']:.2f} ₽\n"
            f"Тариф: {p['name'] if p else '—'}\nТрафик: {cm.gb(c['used_bytes'])}/{l}\nДо: {u}\n"
            f"Шифрование: {'🔒 TLS' if cm.tlson(s) else '⚠️ HTTP'}\n\n{cm.cab(c,s)}\n🔐 Код: {c['access_code']}")
def ktext(c,s): return f"🔑 {c['ext_key']}\n\n📱 VLESS:\n{cm.vless(c,s)}\n\n🔄 Подписка:\n{cm.sub(c,s)}"
@R.message(CommandStart())
async def start(m:Message):
    s=S()
    if adm(m.from_user.id):
        await m.answer("👋 Админ\n/status /stats /clients /regs /certs\n/approve <id> [тариф] /reject <id>\n/topup <email|tg> <сумма>\n/on /off /reset <email>\n/plans /promos\n/newpromo <код> <balance|plan|days> <знач> [лимит] [дней]"); return
    c=me(m.from_user.id)
    if c: await m.answer(mtext(c,s),reply_markup=kb())
    else: await m.answer(f"Вы не зарегистрированы.\nID: {m.from_user.id}\n\n{cm.pbase(s)}")
@R.message(Command("me"))
async def mme(m:Message):
    c=me(m.from_user.id)
    if c: await m.answer(mtext(c,S()),reply_markup=kb())
@R.message(Command("key"))
async def mk(m:Message):
    c=me(m.from_user.id)
    if c: await m.answer(ktext(c,S()))
@R.message(Command("plans"))
async def mpl(m:Message):
    ps=cm.plans()
    if not ps: await m.answer("Тарифы не настроены"); return
    t="💰\n"+"".join(f"• {p['name']} {p['price']:g}₽/{p['period_days']}д\n" for p in ps)
    c=me(m.from_user.id)
    if c: await m.answer(t+f"\nБаланс: {c['balance']:.2f} ₽",reply_markup=pkb())
    else: await m.answer(t)
@R.message(Command("promo"))
async def mpr(m:Message):
    c=me(m.from_user.id)
    if not c: await m.answer("Сначала зарегистрируйтесь"); return
    p=(m.text or "").split(maxsplit=1)
    if len(p)<2: await m.answer("/promo КОД"); return
    s=S(); ok,msg=await asyncio.to_thread(cm.applypromo,c,p[1],s,cm.xui(s))
    await m.answer(("✅ " if ok else "❌ ")+msg,reply_markup=kb())
@R.callback_query(F.data.in_({"menu","me"}))
async def cme(q:CallbackQuery):
    c=me(q.from_user.id)
    if c:
        try: await q.message.edit_text(mtext(c,S()),reply_markup=kb())
        except Exception: pass
    await q.answer()
@R.callback_query(F.data=="plans")
async def cpl(q:CallbackQuery):
    c=me(q.from_user.id)
    try: await q.message.edit_text("💰 Баланс: %.2f ₽"%(c["balance"] if c else 0),reply_markup=pkb())
    except Exception: pass
    await q.answer()
@R.callback_query(F.data=="promo")
async def cp2(q:CallbackQuery):
    await q.answer(); await q.message.answer("🎁 /promo КОД")
@R.callback_query(F.data=="key")
async def ck(q:CallbackQuery):
    c=me(q.from_user.id); await q.answer()
    if c: await q.message.answer(ktext(c,S()))
@R.callback_query(F.data.startswith("buy:"))
async def cbuy(q:CallbackQuery):
    c=me(q.from_user.id); p=cm.plan(q.data.split(":")[1])
    if not c or not p: await q.answer("Ошибка",show_alert=True); return
    b=InlineKeyboardBuilder(); b.button(text=f"✅ {p['price']:g} ₽",callback_data="ok:%d"%p["id"]); b.button(text="⬅️",callback_data="plans"); b.adjust(1)
    try: await q.message.edit_text(f"«{p['name']}» {p['price']:g}₽/{p['period_days']}д\nБаланс {c['balance']:.2f} ₽",reply_markup=b.as_markup())
    except Exception: pass
    await q.answer()
@R.callback_query(F.data.startswith("ok:"))
async def cok(q:CallbackQuery):
    c=me(q.from_user.id); p=cm.plan(q.data.split(":")[1])
    if not c or not p: await q.answer("Ошибка",show_alert=True); return
    await q.answer("…"); s=S()
    ok,msg=await asyncio.to_thread(cm.applyplan,c,p,s,cm.xui(s))
    try: await q.message.edit_text(("✅ " if ok else "❌ ")+msg,reply_markup=kb())
    except Exception: await q.message.answer(msg,reply_markup=kb())
@R.message(Command("status"))
async def ast(m:Message):
    if not adm(m.from_user.id): return
    s=S()
    with cm.db() as c:
        n=c.execute("SELECT COUNT(*) FROM clients").fetchone()[0]
        a=c.execute("SELECT COUNT(*) FROM clients WHERE enabled=1").fetchone()[0]
        p=c.execute("SELECT COUNT(*) FROM registrations WHERE status='pending'").fetchone()[0]
    t=f"📊 {a}/{n} клиентов\n📝 заявок {p}\n🔒 TLS: {cm.tlson(s)}\nIP: {cm.server_ip(s)}\n"
    try:
        r=await asyncio.to_thread(cm.xui(s,8).status); x=(r or {}).get("xray",{})
        t+=f"🟢 xray {x.get('state','?')}"
    except Exception as e: t+=f"🔴 {e}"
    await m.answer(t)
@R.message(Command("certs"))
async def acert(m:Message):
    if not adm(m.from_user.id): return
    s=S(); c,_=cm.tlspaths(s)
    t=f"🔐 {c or 'нет'}\nДоверенный: {cm.cert_trusted(s)}\nTLS-прокси: {cm.tlson(s)}\n\n"
    for x in cm.cert_list(s): t+=f"• {x['cert']} CN={x['cn']} дней={x['days']} ok={x['trusted']}\n"
    await m.answer(t[:3900])
@R.message(Command("stats"))
async def astats(m:Message):
    if not adm(m.from_user.id): return
    with cm.db() as c:
        f=lambda q:c.execute(q).fetchone()[0]
        await m.answer("📈 %d клиентов (%d акт)\nБалансы %.2f₽\nПополнений %.2f₽\nЗаявок %d"%(
          f("SELECT COUNT(*) FROM clients"),f("SELECT COUNT(*) FROM clients WHERE enabled=1"),
          f("SELECT COALESCE(SUM(balance),0) FROM clients"),f("SELECT COALESCE(SUM(amount),0) FROM payments WHERE amount>0"),
          f("SELECT COUNT(*) FROM registrations WHERE status='pending'")))
@R.message(Command("clients"))
async def acl(m:Message):
    if not adm(m.from_user.id): return
    cs=cm.clients()
    if not cs: await m.answer("Нет"); return
    t="\n".join(f"{'🟢' if c['enabled'] else '🔴'} {c['email']} {c['balance']:.0f}₽ {cm.gb(c['used_bytes'])}GB" for c in cs)
    for i in range(0,len(t),3500): await m.answer(t[i:i+3500])
@R.message(Command("topup"))
async def atp(m:Message):
    if not adm(m.from_user.id): return
    p=(m.text or "").split()
    if len(p)<3: await m.answer("/topup <email|tg> <сумма>"); return
    c=cm.client(email=p[1]) or cm.client(tg_id=p[1])
    if not c: await m.answer("Не найден"); return
    try: a=float(p[2].replace(",","."))
    except ValueError: await m.answer("Число"); return
    with cm.db() as con:
        con.execute("UPDATE clients SET balance=ROUND(balance+?,2) WHERE id=?",(a,c["id"]))
        con.execute("INSERT INTO payments(tg_id,amount,source,status) VALUES(?,?,?,?)",(c["tg_id"],a,"bot","paid"))
    c=cm.client(id=c["id"]); s=S(); r=await asyncio.to_thread(cm.activate,c,s,cm.xui(s))
    cm.tg(s,c["tg_id"],f"💰 +{a:.2f} ₽"); await m.answer(f"✅ {c['email']} +{a:.2f}₽ {r}")
async def _sw(m,v):
    if not adm(m.from_user.id): return
    p=(m.text or "").split()
    if len(p)<2: await m.answer("/on|/off <email>"); return
    c=cm.client(email=p[1])
    if not c: await m.answer("Не найден"); return
    with cm.db() as con: con.execute("UPDATE clients SET enabled=? WHERE id=?",(v,c["id"]))
    c["enabled"]=v; s=S()
    try: await asyncio.to_thread(cm.sync,c,s,cm.xui(s))
    except Exception as e: await m.answer("⚠️ %s"%e)
    await m.answer(("🟢 " if v else "🔴 ")+c["email"])
@R.message(Command("on"))
async def aon(m:Message): await _sw(m,1)
@R.message(Command("off"))
async def aoff(m:Message): await _sw(m,0)
@R.message(Command("reset"))
async def ars(m:Message):
    if not adm(m.from_user.id): return
    p=(m.text or "").split()
    if len(p)<2: await m.answer("/reset <email>"); return
    c=cm.client(email=p[1])
    if not c: await m.answer("Не найден"); return
    s=S(); x=cm.xui(s)
    try: await asyncio.to_thread(cm.reset,c,s,x)
    except Exception as e: await m.answer("⚠️ %s"%e)
    c["used_bytes"]=0; c["notified"]=0
    await m.answer("✅ "+await asyncio.to_thread(cm.activate,c,s,x))
@R.message(Command("regs"))
async def arg(m:Message):
    if not adm(m.from_user.id): return
    with cm.db() as c: rows=[dict(r) for r in c.execute("SELECT * FROM registrations WHERE status='pending' ORDER BY id DESC LIMIT 20")]
    if not rows: await m.answer("Нет заявок"); return
    await m.answer("📝\n"+"".join(f"#{r['id']} {r['name']} {r['phone']}\n" for r in rows)+"\n/approve <id> [тариф]")
@R.message(Command("approve"))
async def aap(m:Message):
    if not adm(m.from_user.id): return
    p=(m.text or "").split()
    if len(p)<2: await m.answer("/approve <id> [тариф]"); return
    import uuid as U
    with cm.db() as con: row=con.execute("SELECT * FROM registrations WHERE id=?",(int(p[1]),)).fetchone()
    if not row or row["status"]!="pending": await m.answer("Не найдена"); return
    g=dict(row); s=S(); pl=cm.plan(int(p[2])) if len(p)>2 else None
    em="u"+"".join(ch for ch in g["phone"] if ch.isdigit())
    while cm.client(email=em): em="u"+cm.rnd(6)
    tg=g["tg_id"] or "u_"+cm.rnd(8)
    c={"tg_id":tg,"name":g["name"],"email":em,"uuid":str(U.uuid4()),"balance":0,
       "limit_gb":float(pl["limit_gb"]) if pl else 0,"ext_key":cm.rnd(8,True),"inbound_id":0,
       "http_port":0,"http_user":"","http_pass":"","http_inbound_id":0}
    x=cm.xui(s)
    try: x.add_client(cm.ib(c,s),em,client_uuid=c["uuid"],total_gb=c["limit_gb"])
    except Exception as e: await m.answer("⚠️ %s"%e)
    cert,key=cm.tlspaths(s) if cm.tlson(s) else ("","")
    us={y["http_port"] for y in cm.clients()}
    port=next((q for q in range(int(s["http_port_start"]),int(s["http_port_end"])+1) if q not in us),None)
    if port:
        c["http_port"]=port; c["http_user"]="u"+cm.rnd(6); c["http_pass"]=cm.rnd(16)
        try: c["http_inbound_id"]=x.add_http_inbound(port,c["http_user"],c["http_pass"],"browser-"+em,tls_cert=cert,tls_key=key)
        except Exception: c["http_port"]=0
    with cm.db() as con:
        cur=con.execute("INSERT INTO clients(tg_id,name,email,uuid,balance,limit_gb,used_bytes,enabled,notified,paid_until,ext_key,http_port,http_user,http_pass,http_inbound_id,inbound_id,plan_id,sub_id,access_code) VALUES(?,?,?,?,0,?,0,1,0,0,?,?,?,?,?,0,?,?)",
          (tg,g["name"],em,c["uuid"],c["limit_gb"],c["ext_key"],c["http_port"],c["http_user"],c["http_pass"],c["http_inbound_id"],cm.rnd(16),cm.rnd(6,True)))
        c["id"]=cur.lastrowid
        con.execute("UPDATE registrations SET status='approved',client_id=?,decided_at=datetime('now') WHERE id=?",(c["id"],g["id"]))
    if pl: cm.applyplan(c,pl,s,x,notify=False,free=True)
    c=cm.client(id=c["id"])
    if g["tg_id"]: cm.tg(s,g["tg_id"],f"✅ {cm.cab(c,s)}\nКод {c['access_code']}\nКлюч {c['ext_key']}")
    await m.answer("✅ "+c["email"])
@R.message(Command("reject"))
async def arj(m:Message):
    if not adm(m.from_user.id): return
    p=(m.text or "").split()
    if len(p)<2: await m.answer("/reject <id>"); return
    with cm.db() as con: con.execute("UPDATE registrations SET status='rejected' WHERE id=?",(int(p[1]),))
    await m.answer("Отклонена")
@R.message(Command("newpromo"))
async def anp(m:Message):
    if not adm(m.from_user.id): return
    p=(m.text or "").split()
    if len(p)<4: await m.answer("/newpromo <код> <balance|plan|days> <знач> [лимит] [дней]"); return
    try: v=float(p[3].replace(",",".")); mx=int(p[4]) if len(p)>4 else 0; vd=int(p[5]) if len(p)>5 else 0
    except ValueError: await m.answer("Числа"); return
    ok,msg=cm.mkpromo(p[1],p[2],v,mx,cm.now()+vd*86400 if vd>0 else 0,"bot")
    await m.answer(("✅ " if ok else "❌ ")+msg)
@R.message(Command("promos"))
async def apr(m:Message):
    if not adm(m.from_user.id): return
    ps=cm.promos()
    if not ps: await m.answer("Нет"); return
    await m.answer("🎁\n"+"".join(f"{p['code']} {p['kind']} {p['value']:g} {p['used_count']}/{p['max_uses'] or '∞'}\n" for p in ps))
async def run(token):
    b=Bot(token); d=Dispatcher(); d.include_router(R)
    log.info("бот запущен")
    try: await d.start_polling(b,handle_signals=False)
    finally: await b.session.close()
async def main():
    cm.init_db()
    while True:
        t=S().get("bot_token","").strip()
        if not t: await asyncio.sleep(20); continue
        task=asyncio.create_task(run(t))
        while True:
            await asyncio.sleep(20); cur=S().get("bot_token","").strip()
            if cur!=t or task.done():
                task.cancel()
                try: await task
                except Exception: pass
                if cur==t: await asyncio.sleep(20)
                break
if __name__=="__main__":
    try: asyncio.run(main())
    except KeyboardInterrupt: pass
