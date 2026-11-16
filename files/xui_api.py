import json,secrets,time,uuid as U
import requests,urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
class XUIError(Exception):
    def __init__(s,m,code=0):
        super().__init__(m); s.status=code
_F={}; CD=60
def _j(v):
    if isinstance(v,str):
        try: return json.loads(v)
        except Exception: return {}
    return v or {}
class XUI:
    def __init__(s,base,user="",pw="",token="",timeout=15):
        s.base=(base or "").rstrip("/"); s.user=user; s.pw=pw; s.token=token; s.t=timeout
        s.s=requests.Session(); s.s.verify=False; s.csrf=None; s.ok=False
    def u(s,p): return s.base+"/"+p.lstrip("/")
    def login(s):
        if s.token: s.ok=True; return
        k=(s.base,s.user); un,err=_F.get(k,(0,""))
        if time.time()<un: raise XUIError("пауза после неудачного входа: "+err)
        cs=None
        try:
            j=s.s.get(s.u("/csrf-token"),timeout=s.t).json()
            if j.get("success"): cs=j.get("obj")
        except Exception: pass
        s.csrf=cs; ok=False; code=0; body=""
        for kw in ({"data":{"username":s.user,"password":s.pw}},{"json":{"username":s.user,"password":s.pw}}):
            try:
                h={"X-CSRF-Token":cs} if cs else {}
                r=s.s.post(s.u("/login"),headers=h,timeout=s.t,allow_redirects=False,**kw)
                code=r.status_code; body=r.text[:200]; ok=bool(r.json().get("success"))
            except Exception as e: body=str(e)[:200]
            if ok: break
        if not ok:
            _F[k]=(time.time()+CD,f"HTTP {code} {body}")
            raise XUIError(f"вход в 3x-ui не удался (HTTP {code}): {body}",code)
        _F.pop(k,None); s.ok=True
    def req(s,m,p,retry=True,headers=None,**kw):
        if not s.ok: s.login()
        orig=dict(headers or {}); h=dict(orig); h.setdefault("Accept","application/json")
        if s.token: h["Authorization"]="Bearer "+s.token
        if s.csrf and m.upper()!="GET": h["X-CSRF-Token"]=s.csrf
        try: r=s.s.request(m,s.u(p),headers=h,timeout=s.t,allow_redirects=False,**kw)
        except requests.RequestException as e: raise XUIError("сеть: %s"%e)
        if r.status_code in (401,403,302,307) and retry and not s.token:
            s.ok=False; return s.req(m,p,False,orig,**kw)
        try: j=r.json()
        except Exception:
            if retry and not s.token and r.status_code!=404:
                s.ok=False; return s.req(m,p,False,orig,**kw)
            raise XUIError("неожиданный ответ (HTTP %s) %s"%(r.status_code,p),r.status_code)
        if not j.get("success"): raise XUIError(str(j.get("msg") or j),r.status_code)
        return j.get("obj")
    def any(s,m,paths,**kw):
        last=None
        for p in paths:
            try: return s.req(m,p,**kw)
            except XUIError as e:
                last=e
                if e.status!=404: raise
        raise last
    def get_inbounds(s): return s.req("GET","/panel/api/inbounds/list") or []
    def get_inbound(s,i): return s.req("GET","/panel/api/inbounds/get/%s"%i)
    def clients_list(s):
        try: return s.req("GET","/panel/api/clients/list") or []
        except XUIError:
            out=[]
            for b in s.get_inbounds():
                for c in _j(b.get("settings")).get("clients",[]) or []:
                    c=dict(c); c.setdefault("uuid",c.get("id")); out.append(c)
            return out
    def find(s,email=None,cu=None):
        for c in s.clients_list():
            if email and str(c.get("email"))==str(email): return c
            if cu and (str(c.get("uuid"))==str(cu) or str(c.get("id"))==str(cu)): return c
        return None
    def add_client(s,inbound_id,email,client_uuid=None,total_gb=0,expiry_ms=0,enable=True,flow="xtls-rprx-vision"):
        cu=client_uuid or str(U.uuid4()); iid=int(inbound_id)
        try:
            st=_j(s.get_inbound(iid).get("settings"))
            if "mlkem768" in str(st.get("encryption") or ""): flow=""
        except Exception: pass
        flat={"email":email,"uuid":cu,"flow":flow,"limitIp":0,"totalGB":int(float(total_gb)*2**30),
          "expiryTime":int(expiry_ms),"enable":bool(enable),"tgId":0,"reset":0,"comment":"",
          "subId":secrets.token_hex(8),"inboundIds":[iid]}
        errs=[]
        for body in (flat,dict(flat,id=cu),{"client":flat,"inboundIds":[iid]}):
            try: s.req("POST","/panel/api/clients/add",json=body)
            except XUIError as e: errs.append(str(e)[:110]); continue
            if s.find(email=email,cu=cu): return cu
            errs.append("ok, но клиента нет в списке")
        leg={"id":iid,"settings":json.dumps({"clients":[dict(flat,id=cu)]})}
        for p in ("/panel/api/inbounds/addClient","/panel/api/inbounds/%s/addClient"%iid):
            try:
                s.req("POST",p,json=leg)
                if s.find(email=email,cu=cu): return cu
            except XUIError as e: errs.append(str(e)[:70])
        raise XUIError("создание клиента не удалось: "+" | ".join(errs))
    def update_client(s,inbound_id,cu,**ch):
        c=s.find(cu=cu)
        if not c: raise XUIError("клиент %s не найден"%cu)
        b=dict(c); b.update(ch); b.pop("traffic",None); b["inboundIds"]=c.get("inboundIds") or [int(inbound_id)]
        s.any("POST",["/panel/api/clients/update/%s"%c.get("email"),"/panel/api/clients/update/%s"%cu,
                      "/panel/api/inbounds/updateClient/%s"%cu],json=b)
    def del_client(s,inbound_id,cu):
        c=s.find(cu=cu); k=(c or {}).get("email") or cu
        s.any("POST",["/panel/api/clients/del/%s"%k,"/panel/api/inbounds/%s/delClient/%s"%(inbound_id,cu)])
    def reset_client_traffic(s,*a,**kw):
        iid=None; em=kw.get("email")
        for x in a:
            if isinstance(x,str) and not x.isdigit(): em=x
            else: iid=x
        s.any("POST",["/panel/api/clients/resetTraffic/%s"%em,"/panel/api/inbounds/%s/resetClientTraffic/%s"%(iid or 0,em)])
    def get_client_stats(s,*a,**kw):
        em=kw.get("email")
        if not em:
            for x in a:
                if isinstance(x,str) and not x.isdigit(): em=x
        if not em and a: em=str(a[-1])
        c=s.find(email=em)
        if c:
            t=c.get("traffic") or {}
            if isinstance(t,list): return {"up":sum(int(i.get("up") or 0) for i in t),"down":sum(int(i.get("down") or 0) for i in t)}
            return {"up":int(t.get("up") or 0),"down":int(t.get("down") or 0)}
        try: return s.any("GET",["/panel/api/clients/traffics/%s"%em,"/panel/api/inbounds/getClientTraffics/%s"%em])
        except XUIError: return {"up":0,"down":0}
    def add_http_inbound(s,port,user,pw,remark,total_bytes=0,expiry_ms=0,enable=True,tls_cert="",tls_key=""):
        ss={"network":"tcp","security":"none"}
        if tls_cert and tls_key:
            ss={"network":"tcp","security":"tls","tlsSettings":{"certificates":[{"certificateFile":tls_cert,"keyFile":tls_key}],"alpn":["http/1.1"],"minVersion":"1.2"}}
        s.req("POST","/panel/api/inbounds/add",json={"enable":bool(enable),"remark":remark,"listen":"","port":int(port),
          "protocol":"http","expiryTime":int(expiry_ms),"total":int(total_bytes),
          "settings":json.dumps({"accounts":[{"user":user,"pass":pw}],"allowTransparent":False}),
          "streamSettings":json.dumps(ss),"sniffing":json.dumps({"enabled":True,"destOverride":["http","tls"]})})
        for b in s.get_inbounds():
            if b.get("port")==int(port) and b.get("protocol")=="http": return b["id"]
        raise XUIError("http inbound не найден")
    def update_inbound(s,b):
        p=dict(b)
        for k in ("settings","streamSettings","sniffing"):
            if not isinstance(p.get(k),str): p[k]=json.dumps(p.get(k) or {})
        p.pop("clientStats",None); s.req("POST","/panel/api/inbounds/update/%s"%b["id"],json=p)
    def reset_inbound_traffic(s,i): s.req("POST","/panel/api/inbounds/%s/resetTraffic"%i)
    def del_inbound(s,i): s.req("POST","/panel/api/inbounds/del/%s"%i)
    def status(s):
        try: return s.req("GET","/panel/api/server/status")
        except XUIError: return s.req("POST","/panel/api/server/status")
    def probe(s):
        try:
            if not s.ok: s.login()
        except Exception: pass
        out={}
        for p,ms in [("/panel/api/inbounds/list",("GET",)),("/panel/api/clients/list",("GET",)),
                     ("/panel/api/server/status",("GET",)),("/panel/api/clients/add",("POST",))]:
            r={}
            for m in ms:
                try:
                    h={"Accept":"application/json"}
                    if s.token: h["Authorization"]="Bearer "+s.token
                    if s.csrf and m=="POST": h["X-CSRF-Token"]=s.csrf
                    q=s.s.request(m,s.u(p),headers=h,json={} if m=="POST" else None,timeout=8,allow_redirects=False)
                    r[m]=str(q.status_code)+" "+q.text[:130].replace("\n"," ")
                except Exception as e: r[m]="err "+str(e)[:60]
            out[p]=r
        return out
