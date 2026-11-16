const D={active:false,serverUrl:"",key:"",baseConfig:null,catalog:{presets:{},remote_lists:{}},userChoices:{mode:"whitelist",active_presets:[],custom_domains:[]}};
async function get(){const r=await chrome.storage.local.get("settings");const s=Object.assign({},D,r.settings||{});s.userChoices=Object.assign({},D.userChoices,s.userChoices||{});return s;}
async function put(s){await chrome.storage.local.set({settings:s});}
function dmap(ds){const m={};for(let d of ds){d=String(d||"").trim().toLowerCase().replace(/^\*\./,"").replace(/^\.+/,"").replace(/\.+$/,"");if(d&&/^[a-z0-9.-]+$/i.test(d))m[d]=1;}return m;}
function pac(cfg,mode,ds){
 const p=((cfg.scheme==="https")?"HTTPS ":"PROXY ")+cfg.host+":"+cfg.port;
 const head='function FindProxyForURL(u,h){h=h.toLowerCase();if(isPlainHostName(h)||h==="localhost"||shExpMatch(h,"*.local"))return "DIRECT";var ip=dnsResolve(h);if(ip&&(isInNet(ip,"127.0.0.0","255.0.0.0")||isInNet(ip,"10.0.0.0","255.0.0.0")||isInNet(ip,"172.16.0.0","255.240.0.0")||isInNet(ip,"192.168.0.0","255.255.0.0")))return "DIRECT";var M='+JSON.stringify(dmap(ds))+';function m(x){if(M[x])return true;var i=x.indexOf(".");while(i>0){x=x.slice(i+1);if(M[x])return true;i=x.indexOf(".");}return false;}var hit=m(h);';
 if(mode==="always")return head+'return "'+p+'";}';
 if(mode==="blacklist")return head+'return hit?"DIRECT":"'+p+'";}';
 return head+'return hit?"'+p+'":"DIRECT";}';}
function badge(on,tls){chrome.action.setBadgeText({text:on?(tls?"TLS":"ON"):"OFF"});chrome.action.setBadgeBackgroundColor({color:on?(tls?"#0f9d58":"#16a34a"):"#6b7280"});}
async function apply(s){
 if(!s.active||!s.baseConfig||s.userChoices.mode==="off"){await chrome.proxy.settings.clear({scope:"regular"});badge(false);return;}
 let ds=[...(s.userChoices.custom_domains||[])];const pr=(s.catalog&&s.catalog.presets)||{};
 for(const k of (s.userChoices.active_presets||[]))if(pr[k])ds=ds.concat(pr[k]);
 await chrome.proxy.settings.set({value:{mode:"pac_script",pacScript:{data:pac(s.baseConfig,s.userChoices.mode||"whitelist",ds)}},scope:"regular"});
 badge(true,s.baseConfig.scheme==="https");}
async function ft(u,t=15000){const c=new AbortController();const x=setTimeout(()=>c.abort(),t);try{return await fetch(u,{signal:c.signal,cache:"no-store"});}finally{clearTimeout(x);}}
async function check(){const s=await get();if(!s.active||!s.key||!s.serverUrl)return;
 try{const r=await ft(s.serverUrl+"/api/ping?key="+encodeURIComponent(s.key));
  if(r.status===403){s.active=false;await put(s);await apply(s);return;}
  if(r.ok){const c=await ft(s.serverUrl+"/api/get_config?key="+encodeURIComponent(s.key));
   if(c.ok){const d=await c.json();s.baseConfig=d.base_config;s.catalog=d.catalog;await put(s);await apply(s);}}}catch(e){}}
chrome.runtime.onInstalled.addListener(async()=>{chrome.alarms.create("k",{periodInMinutes:10});await apply(await get());check();});
chrome.runtime.onStartup.addListener(async()=>{chrome.alarms.create("k",{periodInMinutes:10});await apply(await get());check();});
chrome.alarms.onAlarm.addListener(a=>{if(a.name==="k")check();});
chrome.runtime.onMessage.addListener((m,s,rep)=>{(async()=>{try{
 if(m.type==="GET_STATE")rep(await get());
 else if(m.type==="SAVE_STATE"){const x=Object.assign({},D,m.settings||{});x.userChoices=Object.assign({},D.userChoices,x.userChoices||{});await put(x);await apply(x);rep({ok:true});}
 else if(m.type==="CHECK_NOW"){await check();rep(await get());}
 else if(m.type==="LOAD_LIST"){const r=await ft(m.url,45000);if(!r.ok)throw new Error("HTTP "+r.status);
  const t=await r.text();const seen=new Set(),out=[];
  for(let l of t.split(/\r?\n/)){let d=l.trim().toLowerCase().replace(/^\|\|/,"").replace(/\^.*$/,"").replace(/^https?:\/\//,"").replace(/\/.*$/,"").replace(/^\.+/,"");
   if(d&&/^[a-z0-9.-]+\.[a-z]{2,}$/i.test(d)&&!seen.has(d)){seen.add(d);out.push(d);if(out.length>=50000)break;}}
  rep({ok:true,domains:out});}
 else rep({ok:false,error:"unknown"});}catch(e){rep({ok:false,error:String((e&&e.message)||e)});}})();return true;});
chrome.webRequest.onAuthRequired.addListener((d,cb)=>{(async()=>{
 if(d.isProxy){const s=await get();const c=s.baseConfig;
  if(s.active&&c&&c.use_auth){cb({authCredentials:{username:c.username,password:c.password}});return;}}
 cb({});})();},{urls:["<all_urls>"]},["asyncBlocking"]);
