#!/usr/bin/env python3
import http.server,ssl,subprocess,os,secrets,time,hmac,urllib.parse,socketserver
B="/opt/rescue-agent"; TF=B+"/token"
if not os.path.exists(TF):
    open(TF,"w").write(secrets.token_urlsafe(24)); os.chmod(TF,0o600)
TOKEN=open(TF).read().strip()
SVC={"proxy-admin","proxy-web","proxy-bot","proxy-monitor","nginx","ssh","x-ui","web-term","web-files","rescue-agent"}
CMDS={"disk":["df","-h"],"mem":["free","-m"],"ports":["ss","-tulnp"],
 "ps":["ps","-eo","pid,user,%cpu,%mem,etime,cmd","--sort=-%cpu"],"uptime":["uptime"],
 "nginxtest":["nginx","-t"],"netsetup":["bash","/opt/proxy-manager/net-setup.sh"],
 "installerr":["bash","-c","cat /root/pm-install.err 2>/dev/null; tail -40 /root/pm-install.log"]}
def run(a,t=40):
    try:
        r=subprocess.run(a,capture_output=True,text=True,timeout=t); return (r.stdout+r.stderr).strip() or "(пусто)"
    except Exception as e: return "(ошибка %s)"%e
def report():
    L=["=== RESCUE ===",time.strftime("%F %T"),""]
    for s in sorted(SVC): L.append("%-16s %s"%(s,run(["systemctl","is-active",s],6)))
    L+=["",run(["df","-h","/"]),run(["free","-m"]),run(["ss","-tulnp"])]
    for s in ("proxy-admin","proxy-web","nginx"):
        L+=["","--"+s+"--",run(["journalctl","-u",s,"-n","15","--no-pager"])]
    return "\n".join(L)
PAGE="""<!doctype html><meta charset=utf-8><title>Rescue</title><style>
body{font-family:system-ui;background:#0b1020;color:#e7ecf5;padding:24px;max-width:960px;margin:auto}
a{color:#22d3ee;display:inline-block;margin:4px 8px 4px 0;padding:9px 15px;border:1px solid #334155;border-radius:10px;text-decoration:none}
h1{font-size:20px}</style><h1>🛟 Резервный канал</h1><p>Перезапуск:</p>__S__<p>Данные:</p>__C__
<p><a href="/__T__/report">📄 Отчёт</a></p>"""
class H(http.server.BaseHTTPRequestHandler):
    def log_message(self,*a): pass
    def _s(self,c,b,ct="text/plain; charset=utf-8"):
        b=b.encode() if isinstance(b,str) else b
        self.send_response(c); self.send_header("Content-Type",ct)
        self.send_header("Content-Length",str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        u=urllib.parse.urlparse(self.path); p=[x for x in u.path.split("/") if x]
        if not p or not hmac.compare_digest(p[0],TOKEN):
            time.sleep(1.5); return self._s(403,"forbidden")
        r=p[1:]
        if not r:
            s="".join('<a href="/%s/restart/%s">↻ %s</a>'%(TOKEN,x,x) for x in sorted(SVC))
            c="".join('<a href="/%s/cmd/%s">%s</a>'%(TOKEN,k,k) for k in CMDS)
            return self._s(200,PAGE.replace("__T__",TOKEN).replace("__S__",s).replace("__C__",c),"text/html; charset=utf-8")
        if r[0]=="report": return self._s(200,report())
        if r[0]=="restart" and len(r)>1 and r[1] in SVC: return self._s(200,run(["systemctl","restart",r[1]],40) or "ok")
        if r[0]=="cmd" and len(r)>1 and r[1] in CMDS: return self._s(200,run(CMDS[r[1]],120))
        return self._s(404,"not found")
class S(socketserver.ThreadingMixIn,http.server.HTTPServer): daemon_threads=True
if __name__=="__main__":
    cert=key=None
    try:
        import sys; sys.path.insert(0,"/opt/proxy-manager")
        import common as cm; cert,key=cm.tlspaths()
    except Exception: pass
    if not cert and os.path.exists("/etc/pm-web/self.crt"): cert,key="/etc/pm-web/self.crt","/etc/pm-web/self.key"
    srv=S(("0.0.0.0",8444),H)
    if cert:
        ctx=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); ctx.load_cert_chain(cert,key)
        srv.socket=ctx.wrap_socket(srv.socket,server_side=True)
    srv.serve_forever()
