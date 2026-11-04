var E=function(id){return document.getElementById(id)};
var state={running:false,creating:false,round_status:'',total_created:0,today_created:0,current_round_created:0,next_trigger:null};
var accounts=[],emails=[],logs=[];
var curTab='dashboard',sseConn=null;
var _refreshBusy=false;
var BATCH_SELECTION_KEY='hme.batch.selectedAccountIds.v1';
var persistedBatchSelection=loadBatchAccountSelection();
var batchState={initialized:persistedBatchSelection!==null,selectedAccountIds:persistedBatchSelection||{},count:5,label:'',busy:false};

function loadBatchAccountSelection(){
  try{
    var raw=localStorage.getItem(BATCH_SELECTION_KEY);
    if(raw===null)return null;
    var ids=JSON.parse(raw);
    if(!Array.isArray(ids))return null;
    var selected={};
    ids.forEach(function(accId){accId=String(accId||'').trim();if(accId)selected[accId]=true;});
    return selected;
  }catch(error){return null;}
}

function saveBatchAccountSelection(){
  try{localStorage.setItem(BATCH_SELECTION_KEY,JSON.stringify(Object.keys(batchState.selectedAccountIds)));}catch(error){}
}

window.hmeStore={state:state,accounts:accounts,emails:emails,logs:logs,inbox:{accId:'',messages:[],selectedId:''},batch:batchState};

function syncStore(){
  window.hmeStore.state=state;
  window.hmeStore.accounts=accounts;
  window.hmeStore.emails=emails;
  window.hmeStore.logs=logs;
}

function esc(s){
  return String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function escAttr(s){
  return String(s==null?'':s).replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}

var BEIJING_TIME_ZONE='Asia/Shanghai';
var _beijingDateTimeFormatter=new Intl.DateTimeFormat('zh-CN',{
  timeZone:BEIJING_TIME_ZONE,year:'numeric',month:'2-digit',day:'2-digit',
  hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'
});
function parseAppDate(value){
  if(value instanceof Date)return new Date(value.getTime());
  if(typeof value==='number'){
    var timestamp=value;
    if(timestamp>0&&timestamp<1000000000000)timestamp*=1000;
    return new Date(timestamp);
  }
  var raw=String(value==null?'':value).trim();
  if(!raw)return null;
  if(/^\d+(?:\.\d+)?$/.test(raw)){
    var numeric=Number(raw);
    if(numeric>0&&numeric<1000000000000)numeric*=1000;
    return new Date(numeric);
  }
  var normalized=raw;
  if(/^\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?)?$/.test(raw)){
    normalized=raw.replace(' ','T')+'Z';
  }
  var parsed=new Date(normalized);
  return isNaN(parsed.getTime())?null:parsed;
}
function beijingDateParts(value){
  var date=parseAppDate(value);
  if(!date)return null;
  var values={};
  _beijingDateTimeFormatter.formatToParts(date).forEach(function(part){
    if(part.type!=='literal')values[part.type]=part.value;
  });
  return values;
}
function formatBeijingDateTime(value){
  var parts=beijingDateParts(value);
  if(!parts)return value?String(value).replace('T',' '):'';
  return parts.year+'-'+parts.month+'-'+parts.day+' '+parts.hour+':'+parts.minute+':'+parts.second;
}
function formatBeijingClock(value){
  var parts=beijingDateParts(value);
  return parts?parts.hour+':'+parts.minute:'';
}
function formatBeijingDateStamp(value){
  var parts=beijingDateParts(value);
  return parts?parts.year+'-'+parts.month+'-'+parts.day:'';
}
function formatBeijingMailTime(value){
  var parts=beijingDateParts(value);
  if(!parts)return value?String(value).substring(0,16):'';
  var today=beijingDateParts(Date.now());
  var sameDay=today&&today.year===parts.year&&today.month===parts.month&&today.day===parts.day;
  return sameDay?parts.hour+':'+parts.minute:(Number(parts.month)+'月'+Number(parts.day)+'日 '+parts.hour+':'+parts.minute);
}
window.parseAppDate=parseAppDate;
window.formatBeijingDateTime=formatBeijingDateTime;
window.formatBeijingClock=formatBeijingClock;
window.formatBeijingDateStamp=formatBeijingDateStamp;
window.formatBeijingMailTime=formatBeijingMailTime;

async function api(path,opts){
  opts=opts||{};
  var timeout=opts.timeout||12000;
  delete opts.timeout;
  var ctrl=new AbortController();
  var timer=setTimeout(function(){ctrl.abort()},timeout);
  try{
    var r=await fetch(path,Object.assign({signal:ctrl.signal},opts));
    clearTimeout(timer);
    var text=await r.text();
    try{
      return text?JSON.parse(text):{};
    }catch(parseErr){
      return {ok:false,error:'接口返回不是合法 JSON: '+String(text||'').slice(0,120)};
    }
  }catch(e){
    clearTimeout(timer);
    return {ok:false,error:e&&e.name==='AbortError'?'请求超时 ('+(timeout/1000)+'s)':((e&&e.message)||'网络错误')};
  }
}

async function apiSlow(path,opts){
  return api(path,Object.assign({timeout:60000},opts||{}));
}

function setView(tab){
  curTab=tab;
  document.querySelectorAll('.nav-item[data-tab]').forEach(function(n){
    n.classList.toggle('active',n.dataset.tab===tab);
  });
  ['dashboard','emails','batch','codes','inbox','docs','logs'].forEach(function(name){
    var view=E('view-'+name);
    if(view)view.style.display=name===tab?'block':'none';
  });
  var titles={dashboard:'仪表盘',emails:'邮箱列表',batch:'批量创建',codes:'收码台',inbox:'收件箱',docs:'API 文档',logs:'运行日志'};
  if(E('tabTitle'))E('tabTitle').textContent=titles[tab]||tab;
  if(tab==='emails'){
    if(typeof refreshEmails==='function')refreshEmails().then(function(){if(typeof renderAliasTable==='function')renderAliasTable();});
  }
  if(tab==='batch'&&typeof renderBatchPanel==='function')renderBatchPanel();
  if(tab==='codes'){
    if(typeof renderCodeDesk==='function')renderCodeDesk();
    if(typeof loadCodeDesk==='function')loadCodeDesk({force:true});
  }
  if(tab==='inbox'&&typeof updateInboxAccountSelect==='function')updateInboxAccountSelect();
  if(tab==='docs'&&typeof renderDocs==='function')renderDocs();
  if(tab==='logs'&&typeof renderLogs==='function')renderLogs();
  if(typeof window.onAdminViewChanged==='function')window.onAdminViewChanged(tab);
}

document.querySelectorAll('.nav-item[data-tab]').forEach(function(el){
  el.addEventListener('click',function(){setView(this.dataset.tab);});
});

async function refreshAll(opts){
  opts=opts||{};
  if(_refreshBusy)return;
  _refreshBusy=true;
  try{
    var tab=curTab;
    var aReq=api('/api/accounts');
    var sReq=api('/api/state');
    var a=await aReq;
    var s=await sReq;
    accounts=a.accounts||[];
    state=s||state;
    syncStore();
    if(typeof renderSidebar==='function')renderSidebar();
    if(typeof renderDashboard==='function')renderDashboard();
    if(tab==='emails'&&typeof refreshEmails==='function'){
      await refreshEmails({background:!!opts.background});
      if(typeof renderAliasTable==='function')renderAliasTable();
    }
    if(tab==='batch'&&typeof renderBatchPanel==='function')renderBatchPanel();
    if(typeof updateInboxAccountSelect==='function'){
      updateInboxAccountSelect({passive:curTab!=='inbox'||!!opts.background});
    }
    if(tab==='codes'&&typeof renderCodeDesk==='function'&&!opts.background)renderCodeDesk();
    renderSchedulerCard();
  }finally{
    _refreshBusy=false;
  }
}

async function refreshLight(){
  if(_refreshBusy)return;
  var s=await api('/api/state');
  if(s&&s.ok===false)return;
  state=s||state;
  syncStore();
  renderSchedulerCard();
  if(curTab==='batch'&&typeof renderBatchPanel==='function')renderBatchPanel();
}

function schedulerText(){
  if(state.creating)return state.round_status||'创建中...';
  if(!state.running)return '已停止';
  var trigger=Number(state.next_trigger||0);
  if(trigger>0){
    var seconds=Math.max(0,Math.ceil(trigger-Date.now()/1000));
    var minutes=Math.floor(seconds/60);
    var remain=seconds%60;
    var clock=formatBeijingClock(trigger*1000);
    return (seconds>0?(minutes+' 分 '+String(remain).padStart(2,'0')+' 秒后创建'):'即将创建')+' · 预计 '+clock;
  }
  return state.round_status||'等待下轮';
}

function refreshSchedulerCountdown(){
  var copy=document.querySelector('#batchSchedulerSlot .batch-scheduler-copy');
  if(copy)copy.textContent=schedulerText();
}

function renderSchedulerCard(){
  var slot=E('batchSchedulerSlot');
  if(!slot)return;
  var running=!!state.running;
  slot.innerHTML=[
    '<div class="batch-scheduler-card">',
    '<div><div class="batch-scheduler-title"><span class="status-dot '+(running?'online':'offline')+'"></span>调度器</div>',
    '<div class="batch-scheduler-copy">'+esc(schedulerText())+'</div></div>',
    '<button class="btn btn-sm '+(running?'btn-danger':'btn-primary')+'" id="btnSched" onclick="toggleScheduler()">',
    running?'停止':'启动',
    '</button></div>'
  ].join('');
}

function renderBatchPanel(){
  var activeAccs=accounts.filter(function(a){return a.status==='active'});
  var list=E('batchChkGroup');
  if(!list)return;
  if(!batchState.initialized&&activeAccs.length){
    activeAccs.forEach(function(account){batchState.selectedAccountIds[String(account.id||'')]=true;});
    batchState.initialized=true;
    saveBatchAccountSelection();
  }
  var accountMap={};
  accounts.forEach(function(account){accountMap[String(account.id||'')]=true;});
  var selectionChanged=false;
  Object.keys(batchState.selectedAccountIds).forEach(function(accId){
    if(!accountMap[accId]){delete batchState.selectedAccountIds[accId];selectionChanged=true;}
  });
  if(selectionChanged)saveBatchAccountSelection();

  var existing={};
  list.querySelectorAll('.batch-account-chip[data-account-id]').forEach(function(node){
    existing[node.getAttribute('data-account-id')]=node;
  });
  activeAccs.forEach(function(account){
    var accId=String(account.id||'');
    var email=account.icloud_email||account.real_email||account.name||accId;
    var node=existing[accId];
    if(!node){
      node=document.createElement('label');
      node.className='batch-account-chip';
      node.setAttribute('data-account-id',accId);
      var checkbox=document.createElement('input');
      checkbox.type='checkbox';
      checkbox.value=accId;
      checkbox.addEventListener('change',function(){setBatchAccountSelected(accId,checkbox.checked);});
      var name=document.createElement('span');
      name.className='batch-account-name';
      var count=document.createElement('span');
      count.className='batch-account-count';
      node.appendChild(checkbox);
      node.appendChild(name);
      node.appendChild(count);
    }
    node.title=email;
    node.querySelector('input').checked=!!batchState.selectedAccountIds[accId];
    node.querySelector('input').disabled=batchState.busy||!!state.creating;
    node.querySelector('.batch-account-name').textContent=email;
    node.querySelector('.batch-account-count').textContent=(Number(account.alias_total)||0)+' 个邮箱';
    list.appendChild(node);
    delete existing[accId];
  });
  Object.keys(existing).forEach(function(accId){existing[accId].remove();});
  var empty=E('batchAccountEmpty');
  if(!activeAccs.length&&!empty){
    empty=document.createElement('span');
    empty.id='batchAccountEmpty';
    empty.className='batch-account-empty';
    empty.textContent='没有可用账号，请先添加或校验账号';
    list.appendChild(empty);
  }else if(activeAccs.length&&empty){empty.remove();}

  var selectedCount=activeAccs.reduce(function(total,account){return total+(batchState.selectedAccountIds[String(account.id||'')]?1:0);},0);
  var totalAliases=activeAccs.reduce(function(total,account){return total+(Number(account.alias_total)||0);},0);
  if(E('batchAccCount'))E('batchAccCount').textContent='已选 '+selectedCount+' / 可用 '+activeAccs.length+(totalAliases?' · '+totalAliases+' 个邮箱':'');
  if(E('batchCount')&&document.activeElement!==E('batchCount'))E('batchCount').value=String(batchState.count||5);
  if(E('batchLabel')&&document.activeElement!==E('batchLabel'))E('batchLabel').value=batchState.label||'';
  var btn=E('btnBatchExec');
  if(btn){btn.disabled=batchState.busy||!!state.creating||!selectedCount;btn.textContent=state.creating?'已有任务创建中...':(batchState.busy?'提交中...':'开始创建（'+selectedCount+' 个账号）');}
  if(typeof window.mountBatchTools==='function')window.mountBatchTools();
  renderSchedulerCard();
}

function setBatchAccountSelected(accId,checked){
  if(checked)batchState.selectedAccountIds[accId]=true;
  else delete batchState.selectedAccountIds[accId];
  batchState.initialized=true;
  saveBatchAccountSelection();
  renderBatchPanel();
}

function updateBatchCount(value){batchState.count=Math.max(1,Math.min(parseInt(value)||1,20));}
function updateBatchLabel(value){batchState.label=String(value||'');}

async function execBatchCreate(){
  var activeIds={};
  accounts.filter(function(account){return account.status==='active';}).forEach(function(account){activeIds[String(account.id||'')]=true;});
  var ids=Object.keys(batchState.selectedAccountIds).filter(function(accId){return activeIds[accId];});
  if(!ids.length){toast('请勾选至少一个账号',true);return}
  var count=Math.max(1,Math.min(parseInt((E('batchCount')&&E('batchCount').value)||batchState.count||5),20));
  var label=(E('batchLabel')&&E('batchLabel').value.trim())||batchState.label||'';
  batchState.count=count;
  batchState.label=label;
  batchState.busy=true;
  var btn=E('btnBatchExec');
  if(btn){btn.disabled=true;btn.textContent='创建中...';}
  try{
    var d=await apiSlow('/api/create-batch',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({account_ids:ids,count_per_account:count,label:label,create_pickup_links:!!(E('batchCreatePickupLinks')&&E('batchCreatePickupLinks').checked)})});
    if(d.ok&&d.accepted){
      toast('批量创建已开始，后台会按节奏执行');
    }else if(d.ok){
      toast('创建完成: '+(d.total_created||0)+' 个成功');
    }else toast('失败: '+(d.error||'?'),true);
  }finally{
    batchState.busy=false;
    await refreshAll();
    renderBatchPanel();
  }
}

async function toggleScheduler(){
  var act=state.running?'stop':'start';
  var d=await api('/api/scheduler/'+act,{method:'POST'});
  if(d.ok)toast(state.running?'调度器已停止':'调度器已启动');
  else toast(d.error||'调度器操作失败',true);
  await refreshAll({background:true});
}

function exportCSV(){
  var filter=E('aliasFilter')?E('aliasFilter').value:'all';
  var filtered=filter==='all'?emails:emails.filter(function(e){return e.account_id===filter});
  var csv='email,account,label,active\n'+filtered.map(function(e){
    return [e.email||'',e.account_name||e.account_id||'',e.label||'',e.hasOwnProperty('active')?(e.active?'yes':'no'):''].map(function(v){
      return '"'+String(v).replace(/"/g,'""')+'"';
    }).join(',');
  }).join('\n');
  var blob=new Blob(['\uFEFF'+csv],{type:'text/csv'});
  var a=document.createElement('a');
  a.href=URL.createObjectURL(blob);
  a.download='icloud_aliases.csv';
  a.click();
}

function clearLogs(){
  logs=[];
  syncStore();
  renderLogs();
}

async function loadLogs(){
  var d=await api('/api/logs?limit=500');
  if(!d.ok)return;
  var live=logs||[];
  logs=(d.logs||[]).concat(live).slice(-500);
  syncStore();
  if(curTab==='logs')renderLogs();
}

async function cleanupLogs(){
  var d=await api('/api/logs/cleanup',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({days:14})});
  if(d.ok){toast('已清理 '+(d.removed||0)+' 条历史日志');await loadLogs();}
  else toast(d.error||'日志清理失败',true);
}

function toast(msg,isErr){
  var t=E('toast');
  if(!t)return;
  t.textContent=String(msg||'');
  t.style.background=isErr?'var(--red)':'var(--ink)';
  t.style.color='var(--paper)';
  t.classList.add('show');
  setTimeout(function(){t.classList.remove('show')},2200);
}

function connectSSE(){
  if(sseConn){sseConn.close();sseConn=null}
  sseConn=new EventSource('/api/log-stream');
  sseConn.onmessage=function(e){
    try{
      var entry=JSON.parse(e.data);
      logs.push(entry);
      if(logs.length>500)logs=logs.slice(-500);
      syncStore();
      if(curTab==='logs')renderLogs();
      if(entry.msg&&entry.msg.indexOf('创建')>=0)refreshLight();
    }catch(_){}
  };
  sseConn.onerror=function(){
    if(sseConn){sseConn.close();sseConn=null;}
    setTimeout(connectSSE,5000);
  };
  loadLogs();
}

function renderLogs(){
  var f=E('logFeed');
  if(!f)return;
  f.innerHTML=logs.map(function(l){
    return '<div class="log-line '+escAttr(l.level||'info')+'"><span class="log-time" title="北京时间">'+esc(formatBeijingDateTime(l.time||''))+'</span>'+esc(l.msg||'')+'</div>';
  }).join('\n');
  f.scrollTop=f.scrollHeight;
}

function closeModal(id){
  var modal=typeof id==='string'?E(id):id;
  if(modal&&modal.classList&&modal.classList.contains('modal-overlay'))modal.remove();
}
window.closeModal=closeModal;
window.closeAddAccModal=function(){closeModal('addAccModal');};
window.closeAppPwdModal=function(){closeModal('appPwdModal');};

document.addEventListener('click',function(event){
  if(event.target&&event.target.classList&&event.target.classList.contains('modal-overlay')&&event.target.dataset.staticBackdrop!=='true')closeModal(event.target);
});
document.addEventListener('keydown',function(event){
  if(event.key!=='Escape')return;
  var modals=document.querySelectorAll('.modal-overlay');
  if(modals.length&&modals[modals.length-1].dataset.staticBackdrop!=='true')closeModal(modals[modals.length-1]);
});

function renderDocs(){
  var el=E('docsContent');
  if(!el)return;
  var sections=[
    ['账号管理',[['GET','/api/accounts','列出所有账号'],['POST','/api/accounts/add','添加账号'],['POST','/api/accounts/{id}/remove','退出账号'],['POST','/api/accounts/{id}/validate','重新校验账号']]],
    ['隐私邮箱',[['GET','/api/aliases','同步云端别名'],['GET','/api/emails','读取本地创建记录'],['POST','/api/accounts/{id}/create','为指定账号创建别名'],['POST','/api/create-batch','跨账号批量创建']]],
    ['收件箱',[['GET','/api/inbox?refresh=1','刷新全部账号收件箱'],['GET','/api/accounts/{id}/inbox?force=1','刷新指定账号收件箱'],['GET','/api/inbox/search?alias={email}','跨账号查询指定隐私邮箱'],['POST','/api/accounts/{id}/app-password','保存并测试 App 专用密码'],['GET/POST','/api/forward-config','管理账号绑定的 QQ / Microsoft 转发 IMAP']]],
    ['收码台',[['GET','/api/inventory','读取收码库存'],['POST','/api/inventory/check-icloud','检查 iCloud 收件'],['POST','/api/inventory/calibrate-cloud','校准云端收码状态']]],
    ['调度器',[['POST','/api/scheduler/start','启动调度器'],['POST','/api/scheduler/stop','停止调度器'],['GET','/api/auto-stock','读取自动补货配置'],['POST','/api/auto-stock/run','立即补货']]]
  ];
  var h='<div style="max-width:900px">';
  sections.forEach(function(sec){
    h+='<div style="margin-bottom:24px"><div style="font-size:12px;color:var(--ink-faint);letter-spacing:.2em;text-transform:uppercase;margin-bottom:10px;border-bottom:1px solid var(--rule);padding-bottom:4px">'+esc(sec[0])+'</div>';
    sec[1].forEach(function(item){
      var color=item[0]==='GET'?'var(--green)':'var(--red)';
      h+='<div style="margin-bottom:10px;padding:10px 14px;background:var(--paper-dim)"><span style="font-weight:700;color:'+color+';margin-right:12px;font-size:11px">'+item[0]+'</span><code style="font-size:12px">'+esc(item[1])+'</code><div style="color:var(--ink-soft);font-size:12px;margin-top:4px">'+esc(item[2])+'</div></div>';
    });
    h+='</div>';
  });
  el.innerHTML=h+'</div>';
}

setTimeout(function(){
  if(window.refreshAll)window.refreshAll({initial:true});
},0);
connectSSE();
setInterval(refreshLight,10000);
setInterval(refreshSchedulerCountdown,1000);
setInterval(function(){
  if(window.refreshAll)window.refreshAll({background:true});
},30000);
