import logging,subprocess
from apscheduler.schedulers.blocking import BlockingScheduler
from datetime import datetime
import common as cm
logging.basicConfig(level=logging.INFO,format="%(asctime)s %(levelname)s %(message)s")
log=logging.getLogger("monitor")
def traffic():
    s=cm.S(); x=cm.xui(s)
    for c in cm.clients():
        try:
            u=0; st=x.get_client_stats(c["email"])
            if st: u+=int(st.get("up",0))+int(st.get("down",0))
            if c["http_inbound_id"]:
                b=x.get_inbound(c["http_inbound_id"]); u+=int(b.get("up",0))+int(b.get("down",0))
        except Exception as e:
            log.warning("трафик %s: %s",c["email"],e); continue
        with cm.db() as con: con.execute("UPDATE clients SET used_bytes=? WHERE id=?",(u,c["id"]))
        l=float(c["limit_gb"] or 0)
        if l<=0 or not c["enabled"]: continue
        lb=l*2**30
        if u>=lb:
            c["used_bytes"]=u; c["enabled"]=0; cm.save(c)
            try: cm.sync(c,s,x)
            except Exception: pass
            cm.tg(s,c["tg_id"],f"⛔ Лимит {l:g} GB исчерпан. {cm.cab(c,s)}")
        elif u>=0.9*lb and not c["notified"]:
            cm.tg(s,c["tg_id"],f"⚠️ {cm.gb(u)} из {l:g} GB. {cm.cab(c,s)}")
            with cm.db() as con: con.execute("UPDATE clients SET notified=1 WHERE id=?",(c["id"],))
def billing():
    s=cm.S(); x=cm.xui(s); t=cm.now()
    for c in cm.clients():
        if (s["billing_enabled"]=="1" or c.get("plan_id")) and c["paid_until"]<=t:
            log.info("биллинг %s: %s",c["email"],cm.activate(c,s,x))
def certwatch():
    s=cm.S(); c,_=cm.tlspaths(s); prev=s.get("_last_cert","")
    if c and c!=prev:
        cm.setS({"_last_cert":c}); log.info("новый сертификат %s — применяю",c)
        subprocess.Popen(["bash",str(cm.BASE/"net-setup.sh")],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
if __name__=="__main__":
    cm.init_db(); sc=BlockingScheduler()
    sc.add_job(traffic,"interval",minutes=30,next_run_time=datetime.now(),id="t",max_instances=1,coalesce=True)
    sc.add_job(billing,"interval",minutes=5,next_run_time=datetime.now(),id="b",max_instances=1,coalesce=True)
    sc.add_job(certwatch,"interval",minutes=10,id="c",max_instances=1,coalesce=True)
    log.info("монитор запущен")
    try: sc.start()
    except KeyboardInterrupt: pass
