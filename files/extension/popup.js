const $=i=>document.getElementById(i);let S={};
async function load(){S=await chrome.runtime.sendMessage({type:"GET_STATE"});
 const sb=$("srvBlock"),su=$("serverUrl");
 if(sb&&su&&/^https?:\/\/.+/.test(su.value)&&su.value.indexOf("__SERVER_URL__")===-1)sb.style.display="none";
 if(S.active&&S.baseConfig&&S.catalog){$("act").classList.add("hidden");$("ctl").classList.remove("hidden");render();}
 else{$("act").classList.remove("hidden");$("ctl").classList.add("hidden");if(S.serverUrl)$("serverUrl").value=S.serverUrl;}}
function render(){document.querySelectorAll(".mode-btn").forEach(b=>{b.classList.toggle("active",b.dataset.mode===S.userChoices.mode);b.onclick=()=>{S.userChoices.mode=b.dataset.mode;save();};});
 const c=$("chips");c.innerHTML="";const pr=(S.catalog&&S.catalog.presets)||{};
 for(const n of Object.keys(pr)){const e=document.createElement("div");const a=(S.userChoices.active_presets||[]).includes(n);
  e.className="chip"+(a?" active":"");e.textContent=(a?"✓ ":"· ")+n;
  e.onclick=()=>{let l=S.userChoices.active_presets||[];S.userChoices.active_presets=l.includes(n)?l.filter(x=>x!==n):[...l,n];save();};c.appendChild(e);}
 $("custom").value=(S.userChoices.custom_domains||[]).join("\n");
 const tls=S.baseConfig&&S.baseConfig.scheme==="https";
 $("srv").textContent=(tls?"🔒 TLS":"⚠️ без шифрования")+" · "+S.key;badge();}
function badge(){const b=$("badge");if(S.userChoices.mode==="off"||!S.active){b.textContent="Выключен";b.className="badge off";}
 else{const tls=S.baseConfig&&S.baseConfig.scheme==="https";const l={whitelist:"только указанные",blacklist:"все кроме",always:"весь трафик"};
  b.textContent=(tls?"🔒 ":"")+(l[S.userChoices.mode]||"Работает");b.className="badge on";}}
async function save(){render();await chrome.runtime.sendMessage({type:"SAVE_STATE",settings:S});}
function fl(i,t,ok){const e=$(i);e.textContent=t;e.className="st"+(ok===true?" ok":ok===false?" error":"");if(ok===true)setTimeout(()=>{if(e.textContent===t)e.textContent="";},4000);}
$("go").onclick=async()=>{const u=$("serverUrl").value.trim().replace(/\/+$/,""),k=$("key").value.trim().toUpperCase();
 if(!u||!k){fl("actSt","Заполните поля",false);return;}fl("actSt","Проверка…");
 try{const c=new AbortController();const t=setTimeout(()=>c.abort(),15000);
  const r=await fetch(u+"/api/get_config?key="+encodeURIComponent(k),{signal:c.signal});clearTimeout(t);
  if(!r.ok){let m="HTTP "+r.status;try{const j=await r.json();if(j.error)m=j.error;}catch(e){}throw new Error(m);}
  const d=await r.json();S={active:true,serverUrl:u,key:k,baseConfig:d.base_config,catalog:d.catalog,userChoices:{mode:"whitelist",active_presets:["Telegram"],custom_domains:[]}};
  await chrome.runtime.sendMessage({type:"SAVE_STATE",settings:S});fl("actSt","Готово",true);setTimeout(load,600);}
 catch(e){fl("actSt",(e.name==="AbortError"?"Нет ответа":e.message),false);}};
$("saveD").onclick=()=>{S.userChoices.custom_domains=[...new Set($("custom").value.split(/\r?\n/).map(x=>x.trim().toLowerCase()).filter(Boolean))];save();fl("st","Сохранено",true);};
$("sync").onclick=async()=>{fl("st","Обновление…");try{const r=await fetch(S.serverUrl+"/api/get_config?key="+encodeURIComponent(S.key));
 if(r.status===403){await chrome.runtime.sendMessage({type:"SAVE_STATE",settings:{active:false}});load();return;}
 if(!r.ok)throw new Error("HTTP "+r.status);const d=await r.json();S.catalog=d.catalog;S.baseConfig=d.base_config;await save();fl("st","Обновлено",true);}catch(e){fl("st",e.message,false);}};
$("chk").onclick=async()=>{fl("st","Проверка…");S=await chrome.runtime.sendMessage({type:"CHECK_NOW"});if(!S.active){load();return;}render();fl("st","Активен",true);};
async function rl(t){fl("st","Загрузка…");const L=(S.catalog&&S.catalog.remote_lists)||{};const u=t==="tg"?L.telegram_actual:L.all_ru_blocked;
 if(!u){fl("st","Не настроено",false);return;}
 const r=await chrome.runtime.sendMessage({type:"LOAD_LIST",url:u});
 if(r.ok){const s=new Set(S.userChoices.custom_domains||[]);let n=0;r.domains.forEach(d=>{if(!s.has(d)){s.add(d);n++;}});S.userChoices.custom_domains=[...s];await save();fl("st","+"+n,true);}
 else fl("st",r.error,false);}
$("tg").onclick=()=>rl("tg");$("ru").onclick=()=>rl("ru");
$("sug").onclick=()=>{$("sugF").classList.remove("hidden");$("sug").classList.add("hidden");};
$("sugCancel").onclick=()=>{$("sugF").classList.add("hidden");$("sug").classList.remove("hidden");$("sugN").value="";$("sugD").value="";};
$("sugSend").onclick=async()=>{const n=$("sugN").value.trim(),d=$("sugD").value.trim();
 if(!n||!d){fl("sugSt","Заполните",false);return;}
 try{const r=await fetch(S.serverUrl+"/api/suggest_preset",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({key:S.key,name:n,domains:d})});
  if(!r.ok){let m="HTTP "+r.status;try{const j=await r.json();if(j.error)m=j.error;}catch(e){}throw new Error(m);}
  fl("sugSt","Отправлено",true);setTimeout(()=>$("sugCancel").click(),2000);}catch(e){fl("sugSt",e.message,false);}};
$("reset").onclick=async()=>{if(confirm("Удалить код?")){await chrome.runtime.sendMessage({type:"SAVE_STATE",settings:{active:false}});load();}};
load();
