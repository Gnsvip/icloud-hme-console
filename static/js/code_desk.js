(function(){
  var codeState={items:[],summary:{},group:'unused',q:'',account_id:'',busy:false,page:1,pageSize:20,scanLimit:50,lastSig:'',reqSeq:0};
  var pickupRecordState={rows:[],q:'',page:1,pageSize:50,total:0,pages:1,loaded:false,selectedIds:{}};
  var groupNames={unused:'未使用',finished:'已使用',trash:'垃圾箱',disabled:'已停用',all:'全部'};
  var autoStockConfigCache=null,autoStockReqSeq=0,autoStockAccountSig='';
  function ce(s){return typeof esc==='function'?esc(s==null?'':s):String(s==null?'':s)}
  function ca(s){return typeof escAttr==='function'?escAttr(s==null?'':s):String(s==null?'':s)}
  function formatPickupRecordTime(value){
    var formatted=formatBeijingDateTime(value);
    return formatted||'-';
  }
  function status(msg,err){
    var el=E('codeDeskStatus');
    if(!el)return;
    el.textContent=msg||'';
    el.className='code-status '+(err?'err':(msg?'ok':''));
  }
  function mountBatchTools(){
    var batchBody=document.querySelector('#view-batch .panel-body');
    if(!batchBody)return;
    var scheduler=E('batchSchedulerSlot');
    var slot=E('batchAutoStockSlot');
    if(!slot){
      slot=document.createElement('div');
      slot.id='batchAutoStockSlot';
      if(scheduler)batchBody.insertBefore(slot,scheduler);
      else batchBody.appendChild(slot);
    }
    slot.className='batch-auto-card';
    var accountSig=(accounts||[]).map(function(account){return [account.id,account.status,account.icloud_email,account.real_email].join(':');}).join('|');
    if(!slot.getAttribute('data-mounted')||accountSig!==autoStockAccountSig){
      slot.setAttribute('data-mounted','1');
      autoStockAccountSig=accountSig;
      renderBatchAutoStockInline();
    }
  }
  window.mountBatchTools=mountBatchTools;
  function activeAutoStockAccounts(){
    return (accounts||[]).filter(function(account){return account.status==='active';});
  }
  function autoStockAccountIds(value){
    if(!Array.isArray(value))return [];
    var seen={};
    return value.map(function(accountId){return String(accountId||'').trim();}).filter(function(accountId){
      if(!accountId||seen[accountId])return false;
      seen[accountId]=true;
      return true;
    });
  }
  function autoStockFormConfig(){
    var fallback=autoStockConfigCache||{};
    var checks=Array.prototype.slice.call(document.querySelectorAll('#stockAccountMenu input[data-account-id]'));
    var allBox=E('stockAllAccounts');
    return {
      enabled:E('stockEnabled')?E('stockEnabled').checked:!!fallback.enabled,
      all_accounts:allBox?allBox.checked:(fallback.hasOwnProperty('all_accounts')?!!fallback.all_accounts:true),
      account_ids:checks.length?checks.filter(function(input){return input.checked;}).map(function(input){return input.getAttribute('data-account-id');}):autoStockAccountIds(fallback.account_ids),
      prefix:E('stockPrefix')?E('stockPrefix').value:(fallback.prefix||'stock'),
      target:parseInt(E('stockTarget')?E('stockTarget').value:(fallback.target||20)),
      batch:parseInt(E('stockBatch')?E('stockBatch').value:(fallback.batch||5))
    };
  }
  function autoStockConfig(cfg){
    cfg=cfg||autoStockConfigCache||{};
    var accountIds=autoStockAccountIds(cfg.account_ids);
    if(!accountIds.length&&cfg.account_id)accountIds=[String(cfg.account_id)];
    var allAccounts=cfg.hasOwnProperty('all_accounts')?!!cfg.all_accounts:!accountIds.length;
    return {
      enabled:!!cfg.enabled,
      all_accounts:allAccounts,
      account_ids:allAccounts?[]:accountIds,
      prefix:cfg.prefix||'stock',
      target:parseInt(cfg.target||20),
      batch:parseInt(cfg.batch||5)
    };
  }
  function autoStockAccountPicker(cfg){
    var activeAccounts=activeAutoStockAccounts();
    var selected={};
    cfg.account_ids.forEach(function(accountId){selected[accountId]=true;});
    var selectedCount=cfg.all_accounts?activeAccounts.length:activeAccounts.reduce(function(total,account){return total+(selected[String(account.id||'')]?1:0);},0);
    var summary=cfg.all_accounts?'全部可用账号':'已选 '+selectedCount+' / '+activeAccounts.length;
    var rows=activeAccounts.map(function(account){
      var accountId=String(account.id||'');
      var label=account.icloud_email||account.real_email||account.name||accountId;
      return '<label class="batch-auto-account-option"><input type="checkbox" data-account-id="'+ca(accountId)+'" '+((cfg.all_accounts||selected[accountId])?'checked':'')+' onchange="setAutoStockAccountSelected(this)"><span>'+ce(label)+'</span></label>';
    }).join('');
    if(!rows)rows='<div class="batch-auto-account-empty">没有可用账号</div>';
    return '<div class="batch-auto-account-picker" id="stockAccountPicker"><button type="button" class="batch-auto-account-toggle" id="stockAccountToggle" aria-expanded="false" onclick="toggleAutoStockAccounts(event)"><span id="stockAccountSummary">'+ce(summary)+'</span><i aria-hidden="true"></i></button><div class="batch-auto-account-menu" id="stockAccountMenu" hidden><label class="batch-auto-account-option batch-auto-account-all"><input type="checkbox" id="stockAllAccounts" '+(cfg.all_accounts?'checked':'')+' onchange="setAutoStockAllAccounts(this.checked)"><span>全部可用账号</span></label>'+rows+'</div></div>';
  }
  function updateAutoStockAccountSummary(){
    var summary=E('stockAccountSummary');
    var allBox=E('stockAllAccounts');
    var checks=Array.prototype.slice.call(document.querySelectorAll('#stockAccountMenu input[data-account-id]'));
    if(summary)summary.textContent=allBox&&allBox.checked?'全部可用账号':'已选 '+checks.filter(function(input){return input.checked;}).length+' / '+checks.length;
  }
  window.toggleAutoStockAccounts=function(event){
    if(event)event.stopPropagation();
    var menu=E('stockAccountMenu');
    var toggle=E('stockAccountToggle');
    if(!menu)return;
    menu.hidden=!menu.hidden;
    if(toggle)toggle.setAttribute('aria-expanded',menu.hidden?'false':'true');
  };
  window.setAutoStockAllAccounts=function(checked){
    if(checked)document.querySelectorAll('#stockAccountMenu input[data-account-id]').forEach(function(input){input.checked=true;});
    updateAutoStockAccountSummary();
  };
  window.setAutoStockAccountSelected=function(input){
    var allBox=E('stockAllAccounts');
    var checks=Array.prototype.slice.call(document.querySelectorAll('#stockAccountMenu input[data-account-id]'));
    if(allBox&&allBox.checked&&!input.checked)allBox.checked=false;
    if(allBox&&checks.length&&checks.every(function(item){return item.checked;}))allBox.checked=true;
    updateAutoStockAccountSummary();
  };
  document.addEventListener('click',function(event){
    var picker=E('stockAccountPicker');
    var menu=E('stockAccountMenu');
    var toggle=E('stockAccountToggle');
    if(picker&&menu&&!picker.contains(event.target)){
      menu.hidden=true;
      if(toggle)toggle.setAttribute('aria-expanded','false');
    }
  });
  function renderAutoStockControls(slot,cfg,flashText,isErr){
    cfg=autoStockConfig(cfg);
    slot.innerHTML='<div class="batch-auto-head"><div><div class="batch-service-title">自动补货</div><div class="batch-service-copy">'+(cfg.enabled?'开启':'关闭')+'</div></div><label class="batch-mini-switch"><input id="stockEnabled" type="checkbox" '+(cfg.enabled?'checked':'')+'><span>启用</span></label></div><div class="batch-auto-grid"><label class="batch-auto-field">账号 '+autoStockAccountPicker(cfg)+'</label><label class="batch-auto-field">标签 <input id="stockPrefix" type="text" value="'+ca(cfg.prefix||'stock')+'" placeholder="stock"></label><label class="batch-auto-field">本轮 <input id="stockTarget" type="number" min="0" value="'+ca(cfg.target||20)+'"></label><label class="batch-auto-field">每批 <input id="stockBatch" type="number" min="1" max="5" value="'+ca(cfg.batch||5)+'"></label></div><div class="batch-service-actions"><button class="btn btn-outline btn-sm" onclick="saveAutoStockModal()">保存</button><button class="btn btn-primary btn-sm" onclick="runAutoStockNow()">立即补货</button></div><div class="batch-auto-msg '+(flashText?(isErr?'err':'ok'):'')+'" id="autoStockMsg">'+ce(flashText||'')+'</div>';
  }
  async function renderBatchAutoStockInline(flashText,isErr){
    var slot=E('batchAutoStockSlot');
    if(!slot||typeof api!=='function')return;
    var seq=++autoStockReqSeq;
    renderAutoStockControls(slot,autoStockConfigCache||autoStockFormConfig(),flashText,isErr);
    try{
      var d=await api('/api/auto-stock');
      if(seq!==autoStockReqSeq)return;
      var cfg=(d&&d.config)||{};
      autoStockConfigCache=cfg;
      renderAutoStockControls(slot,cfg,flashText,isErr);
    }catch(e){
      if(seq!==autoStockReqSeq)return;
      var msg=E('autoStockMsg');
      if(msg&&!flashText){msg.className='batch-auto-msg err';msg.textContent='读取失败';}
    }
  }
  function refreshBatchAutoStockText(flashText,isErr){
    renderBatchAutoStockInline(flashText,isErr);
  }
  function codePageSize(){
    var el=E('codePageSize');
    var n=parseInt((el&&el.value)||codeState.pageSize||20);
    return [10,20,50,100].indexOf(n)>=0?n:20;
  }
  function codeScanLimit(){
    var el=E('codeScanLimit');
    var n=parseInt((el&&el.value)||codeState.scanLimit||50);
    return n>0?n:0;
  }
  function codePagerHtml(total){
    var size=codePageSize();
    var pages=Math.max(1,Math.ceil(total/size));
    if(codeState.page>pages)codeState.page=pages;
    var from=total?((codeState.page-1)*size+1):0;
    var to=Math.min(total,codeState.page*size);
    return '<span>第 '+codeState.page+' / '+pages+' 页 · '+from+'-'+to+' / '+total+'</span><button '+(codeState.page<=1?'disabled':'')+' onclick="setCodePage('+(codeState.page-1)+')">上一页</button><button '+(codeState.page>=pages?'disabled':'')+' onclick="setCodePage('+(codeState.page+1)+')">下一页</button>';
  }
  function updateCodePager(total){
    ensureCodeControls();
    var p=E('codePagerInline');
    if(p)p.innerHTML=codePagerHtml(total||0);
  }
  function ensureCodeControls(){
    var toolbar=document.querySelector('#view-codes .code-toolbar');
    var statusEl=E('codeDeskStatus');
    if(!toolbar||!statusEl)return;
    if(!E('codePageSize')){
      statusEl.insertAdjacentHTML('beforebegin','<label class="code-mini-field">查件数量 <select id="codeScanLimit" onchange="codeState.scanLimit=parseInt(this.value)||50"><option value="10">10</option><option value="20">20</option><option value="50" selected>50</option><option value="100">100</option><option value="200">200</option></select></label><label class="code-mini-field">每页 <select id="codePageSize" onchange="setCodePageSize(this.value)"><option value="10">10</option><option value="20" selected>20</option><option value="50">50</option><option value="100">100</option></select></label>');
    }
    if(!E('codePagerInline')){
      statusEl.insertAdjacentHTML('beforebegin','<span id="codePagerInline" class="code-pager"></span>');
    }
  }
  window.setCodePageSize=function(value){
    codeState.pageSize=parseInt(value)||20;
    codeState.page=1;
    renderCodeDesk();
  };
  window.setCodePage=function(page){
    codeState.page=Math.max(1,parseInt(page)||1);
    renderCodeDesk();
  };
  function install(){
    ensureCodeControls();
    mountBatchTools();
  }
  function refreshAccounts(){
    var sel=E('codeAccountFilter');
    if(!sel)return;
    var old=codeState.account_id||sel.value;
    sel.innerHTML='<option value="">全部账号</option>';
    (accounts||[]).forEach(function(a){
      var name=(a.icloud_email||a.real_email||a.name||a.id||'').substring(0,34);
      sel.innerHTML+='<option value="'+ca(a.id)+'">'+ce(name)+'</option>';
    });
    sel.value=old&&Array.prototype.some.call(sel.options,function(o){return o.value===old})?old:'';
    codeState.account_id=sel.value;
  }
  window.setCodeAccountFilter=function(value){
    codeState.account_id=value||'';
    codeState.page=1;
    var sel=E('codeAccountFilter');
    if(sel&&sel.value!==codeState.account_id)sel.value=codeState.account_id;
    renderCodeDesk();
    if(!codeState.items.length&&!codeState.busy)loadCodeDesk({force:true});
  };
  window.loadCodeDesk=async function(opts){
    opts=opts||{};
    if(codeState.busy&&!opts.force)return;
    codeState.busy=true;
    refreshAccounts();
    var reqSeq=++codeState.reqSeq;
    if(!codeState.items.length)E('codeDeskBody').innerHTML='<div class="code-empty">正在加载库存...</div>';
    try{
      var d=await api('/api/inventory?group=all',{timeout:30000});
      if(reqSeq!==codeState.reqSeq)return;
      if(!d.ok){status(d.error||'加载失败',true);return;}
      codeState.items=d.items||[];
      codeState.summary=d.summary||{};
      refreshAccounts();
      renderCodeDesk();
      status('已加载 '+codeState.items.length+' 个地址',false);
    }finally{
      if(reqSeq===codeState.reqSeq)codeState.busy=false;
    }
  };
  window.setCodeGroup=function(group){
    codeState.group=group||'unused';
    codeState.page=1;
    document.querySelectorAll('.code-tab').forEach(function(b){b.classList.toggle('active',b.dataset.codeGroup===codeState.group);});
    renderCodeDesk();
  };
  window.setCodeSearch=function(value){
    codeState.q=value||'';
    codeState.page=1;
    if(String(codeState.q).trim()){
      codeState.group='all';
      document.querySelectorAll('.code-tab').forEach(function(b){b.classList.toggle('active',b.dataset.codeGroup==='all');});
    }
    renderCodeDesk();
  };
  function basePickupEmail(value){
    var email=String(value||'').trim().toLowerCase();
    var at=email.lastIndexOf('@');
    if(at<=0)return email;
    var local=email.slice(0,at);
    var domain=email.slice(at+1);
    if(['icloud.com','icloud.com.cn','me.com','mac.com'].indexOf(domain)<0)return email;
    var plus=local.indexOf('+');
    return plus>0?local.slice(0,plus)+'@'+domain:email;
  }
  function codeQueryMatches(item,q){
    if(!q)return true;
    var hay=[item.email,item.label,item.remark,item.code,item.subject,item.account_email,item.icloud_email].join(' ').toLowerCase();
    if(hay.indexOf(q)>=0)return true;
    var base=basePickupEmail(q);
    return base!==q&&String(item.email||'').trim().toLowerCase()===base;
  }
  function codeQueryView(item,q){
    var base=basePickupEmail(q);
    if(q&&base!==q&&String(item.email||'').trim().toLowerCase()===base){
      var row=Object.assign({},item);
      row.pickup_email=q;
      return row;
    }
    return item;
  }
  function filtered(group){
    var q=String(codeState.q||'').trim().toLowerCase();
    return (codeState.items||[]).filter(function(item){
      var disabled=item.lifecycle_status==='disabled';
      if(group==='disabled'&&!disabled)return false;
      if(group&&group!=='all'&&group!=='disabled'&&(item.group||'unused')!==group)return false;
      if(group!=='all'&&group!=='disabled'&&disabled)return false;
      if(codeState.account_id&&item.account_id!==codeState.account_id)return false;
      return codeQueryMatches(item,q);
    }).map(function(item){return codeQueryView(item,q);});
  }
  function currentSummaryRows(){
    var q=String(codeState.q||'').trim().toLowerCase();
    return (codeState.items||[]).filter(function(item){
      if(codeState.account_id&&item.account_id!==codeState.account_id)return false;
      return codeQueryMatches(item,q);
    });
  }
  function countSummary(rows){
    var s={all:0,unused:0,finished:0,trash:0,disabled:0,unread:0,with_code:0};
    (rows||[]).forEach(function(item){
      var group=item.group||'unused';
      s.all++;
      if(s.hasOwnProperty(group))s[group]++;
      if(item.lifecycle_status==='disabled')s.disabled++;
      if(item.unread)s.unread++;
      if(item.code)s.with_code++;
    });
    return s;
  }
  function renderSummary(){
    var s=countSummary(currentSummaryRows());
    var total=s.all||0;
    E('codeSummary').innerHTML=[['地址',total],['未使用',s.unused||0],['已使用',s.finished||0],['垃圾箱',s.trash||0],['已停用',s.disabled||0],['未读',s.unread||0],['含验证码',s.with_code||0]].map(function(x){return '<div class="code-summary-card"><span>'+x[0]+'</span><b>'+x[1]+'</b></div>';}).join('');
    document.querySelectorAll('.code-tab').forEach(function(b){
      var g=b.dataset.codeGroup;
      var count=g==='all'?total:(s[g]||0);
      b.textContent=groupNames[g]+' '+count;
    });
  }
  window.renderCodeDesk=function(){
    renderSummary();
    var body=E('codeDeskBody');
    if(!body)return;
    var group=codeState.group||'unused';
    var sig=[group,codeState.account_id||'',codeState.q||''].join('|');
    if(sig!==codeState.lastSig){
      codeState.lastSig=sig;
      codeState.page=1;
    }
    var rows=filtered(group);
    updateCodePager(rows.length);
    body.className='code-table-wrap';
    if(!rows.length){
      body.innerHTML='<div class="code-empty">暂无'+(groupNames[group]||'')+'地址</div>';
      return;
    }
    var size=codePageSize();
    var pages=Math.max(1,Math.ceil(rows.length/size));
    if(codeState.page>pages)codeState.page=pages;
    var start=(codeState.page-1)*size;
    var pageRows=rows.slice(start,start+size);
    body.innerHTML='<div class="code-table"><div class="code-row code-head"><div>状态</div><div>邮箱</div><div>验证码</div><div>标签</div><div>备注</div><div>最近邮件</div><div>操作</div></div>'+pageRows.map(rowHtml).join('')+'</div>';
  };
  var codeMoreIcon='<span class="code-more-dots" aria-hidden="true"><i></i><i></i><i></i></span>';
  window.closeCodeActionMenu=function(){
    var m=E('codeActionMenu');
    if(m)m.remove();
    document.removeEventListener('click',closeCodeActionMenu);
  };
  window.openCodeActionMenu=function(email,btn,pickupEmail){
    closeCodeActionMenu();
    var rect=btn.getBoundingClientRect();
    var menu=document.createElement('div');
    menu.id='codeActionMenu';
    menu.className='code-action-popover';
    menu.innerHTML='<button onclick="handleCodeAction(&quot;'+ca(pickupEmail||email)+'&quot;,&quot;pickup-link&quot;)">取码链接</button><button onclick="handleCodeAction(&quot;'+ca(email)+'&quot;,&quot;read&quot;)">设为已读</button><button onclick="handleCodeAction(&quot;'+ca(email)+'&quot;,&quot;finished&quot;)">标记已用</button><button onclick="handleCodeAction(&quot;'+ca(email)+'&quot;,&quot;unused&quot;)">标记未用</button>';
    document.body.appendChild(menu);
    var top=Math.min(rect.bottom+8,window.innerHeight-menu.offsetHeight-12);
    var left=Math.max(12,Math.min(rect.right-menu.offsetWidth,window.innerWidth-menu.offsetWidth-12));
    menu.style.top=top+'px';
    menu.style.left=left+'px';
    setTimeout(function(){document.addEventListener('click',closeCodeActionMenu);},0);
  };
  window.closePickupLinkModal=function(){
    var modal=E('pickupLinkModal');
    if(modal)modal.remove();
  };
  window.openPickupLink=async function(email){
    closeCodeActionMenu();
    closePickupLinkModal();
    var data=await api('/api/pickup-links/for-email/'+encodeURIComponent(email),{method:'POST'});
    if(!data.ok||!data.pickup_url){status(data.error||'取码链接生成失败',true);return;}
    window.dispatchEvent(new CustomEvent('pickup-links-updated'));
    var absolute=location.origin+data.pickup_url;
    var exportValue=email+'----'+absolute;
    var html='<div class="modal-overlay" id="pickupLinkModal" onclick="if(event.target===this)closePickupLinkModal()"><div class="modal-box"><h3><i class="diamond"></i> 邮箱取码链接</h3><p>'+ce(email)+'</p><textarea class="pickup-link-value" id="pickupLinkValue" readonly rows="3">'+ce(exportValue)+'</textarea><div class="modal-actions"><button class="btn btn-outline" onclick="navigator.clipboard.writeText(E(&quot;pickupLinkValue&quot;).value);status(&quot;邮箱和取码链接已复制&quot;,false)">复制</button><button class="btn btn-primary" onclick="window.open(&quot;'+ca(data.pickup_url)+'&quot;,&quot;_blank&quot;)">打开</button></div></div></div>';
    document.body.insertAdjacentHTML('beforeend',html);
  };
  window.closePickupBatchModal=function(){
    var modal=E('pickupBatchModal');
    if(modal)modal.remove();
  };
  window.openPickupBatchModal=function(seedEmail){
    closeCodeActionMenu();
    closePickupBatchModal();
    pickupRecordState={rows:[],q:'',page:1,pageSize:50,total:0,pages:1,loaded:false,selectedIds:{}};
    var html=[
      '<div class="modal-overlay" id="pickupBatchModal" data-static-backdrop="true">',
      '<div class="modal-box pickup-batch-modal"><button type="button" class="pickup-modal-close" title="关闭" aria-label="关闭" onclick="closePickupBatchModal()">&times;</button><h3><i class="diamond"></i> 取码链接</h3>',
      '<div class="pickup-link-tabs" role="tablist"><button type="button" class="pickup-link-tab active" data-pickup-tab="batch" onclick="switchPickupLinkTab(&quot;batch&quot;)">批量生成</button><button type="button" class="pickup-link-tab" data-pickup-tab="records" onclick="switchPickupLinkTab(&quot;records&quot;)">生成记录</button></div>',
      '<section id="pickupBatchPane"><label class="pickup-batch-label" for="pickupBatchEmails">邮箱，每行一个</label><textarea class="pickup-batch-input" id="pickupBatchEmails" rows="8" placeholder="name@icloud.com">'+ce(seedEmail||'')+'</textarea><div class="pickup-random-row"><label for="pickupAliasCount"><span>额外别名数量</span><input id="pickupAliasCount" type="number" min="0" max="100" step="1" value="1" inputmode="numeric"></label><p>原邮箱始终生成；0 仅原邮箱，1～100 再生成对应数量的 8 位随机 +标签。</p></div><div class="pickup-batch-status" id="pickupBatchStatus"></div><section id="pickupBatchResult" hidden><textarea class="pickup-link-value pickup-batch-output" id="pickupBatchOutput" readonly rows="9"></textarea><div class="pickup-batch-errors" id="pickupBatchErrors"></div></section><div class="modal-actions"><button class="btn btn-outline" type="button" onclick="closePickupBatchModal()">取消</button><button class="btn btn-primary" type="button" id="pickupBatchGenerate" onclick="generatePickupLinksBatch()">生成链接</button><button class="btn btn-outline" type="button" id="pickupBatchCopy" onclick="copyPickupBatchLinks()" hidden>复制</button><button class="btn btn-primary" type="button" id="pickupBatchDownload" onclick="downloadPickupBatchLinks()" hidden>下载 TXT</button></div></section>',
      '<section id="pickupRecordPane" hidden><div class="pickup-record-toolbar"><input type="text" id="pickupRecordSearch" class="pickup-record-search" placeholder="搜索邮箱" onkeydown="if(event.key===&quot;Enter&quot;)searchPickupRecords()"><button type="button" class="btn btn-outline btn-sm" onclick="searchPickupRecords()">查询</button></div><div class="pickup-record-selection"><label><input type="checkbox" id="pickupRecordSelectAll" onchange="selectPickupRecordPage(this.checked)"><span>全选本页</span></label><span class="pickup-record-summary" id="pickupRecordSummary">正在读取记录...</span><button type="button" class="btn btn-danger btn-sm" id="pickupRecordRevokeSelected" onclick="requestRevokePickupLinks()" disabled>批量失效</button></div><div class="pickup-record-list" id="pickupRecordList"></div><div class="pickup-record-pager"><button type="button" class="btn btn-outline btn-sm" id="pickupRecordPrev" onclick="changePickupRecordPage(-1)">上一页</button><span id="pickupRecordPageInfo">1 / 1</span><button type="button" class="btn btn-outline btn-sm" id="pickupRecordNext" onclick="changePickupRecordPage(1)">下一页</button></div><div class="modal-actions"><button class="btn btn-outline" type="button" onclick="closePickupBatchModal()">关闭</button><button class="btn btn-outline" type="button" id="pickupRecordCopy" onclick="copyPickupRecordPage()" disabled>复制本页</button><button class="btn btn-primary" type="button" id="pickupRecordDownload" onclick="downloadPickupRecordHistory()" disabled>下载记录</button></div></section>',
      '</div></div>'
    ].join('');
    document.body.insertAdjacentHTML('beforeend',html);
    var input=E('pickupBatchEmails');
    if(input){input.focus();input.setSelectionRange(input.value.length,input.value.length);}
  };
  window.switchPickupLinkTab=function(tab){
    var records=tab==='records';
    E('pickupBatchPane').hidden=records;
    E('pickupRecordPane').hidden=!records;
    document.querySelectorAll('[data-pickup-tab]').forEach(function(button){button.classList.toggle('active',button.dataset.pickupTab===tab);});
    if(records&&!pickupRecordState.loaded)loadPickupRecords();
  };
  function pickupRecordLine(item){
    return item.email+'----'+location.origin+item.pickup_url;
  }
  function renderPickupRecords(){
    var list=E('pickupRecordList');
    if(!list)return;
    list.innerHTML=pickupRecordState.rows.length?pickupRecordState.rows.map(function(item){
      var line=pickupRecordLine(item);
      var absolute=location.origin+item.pickup_url;
      var created=formatPickupRecordTime(item.created_at);
      return '<div class="pickup-record-row"><label class="pickup-record-check" title="选择这条链接"><input type="checkbox" data-pickup-record-id="'+ca(item.id)+'" '+(pickupRecordState.selectedIds[item.id]?'checked':'')+' onchange="setPickupRecordSelected(&quot;'+ca(item.id)+'&quot;,this.checked)"><span></span></label><div class="pickup-record-main"><strong title="'+ca(item.email)+'">'+ce(item.email)+'</strong><span class="pickup-record-url" title="'+ca(absolute)+'">'+ce(absolute)+'</span></div><time title="北京时间">'+ce(created)+'</time><div class="pickup-record-actions"><button type="button" onclick="copyPickupRecord(&quot;'+ca(line)+'&quot;)">复制</button><button type="button" onclick="window.open(&quot;'+ca(item.pickup_url)+'&quot;,&quot;_blank&quot;)">打开</button><button type="button" class="danger" onclick="requestRevokePickupLinks([&quot;'+ca(item.id)+'&quot;])">失效</button></div></div>';
    }).join(''):'<div class="pickup-record-empty">没有生成记录</div>';
    var selectedCount=Object.keys(pickupRecordState.selectedIds).length;
    E('pickupRecordSummary').textContent='共 '+pickupRecordState.total+' 条有效记录'+(selectedCount?' · 已选 '+selectedCount:'');
    E('pickupRecordPageInfo').textContent=pickupRecordState.page+' / '+pickupRecordState.pages;
    E('pickupRecordPrev').disabled=pickupRecordState.page<=1;
    E('pickupRecordNext').disabled=pickupRecordState.page>=pickupRecordState.pages;
    E('pickupRecordCopy').disabled=!pickupRecordState.rows.length;
    E('pickupRecordDownload').disabled=!pickupRecordState.total;
    E('pickupRecordRevokeSelected').disabled=!selectedCount;
    var selectAll=E('pickupRecordSelectAll');
    var pageSelected=pickupRecordState.rows.filter(function(item){return pickupRecordState.selectedIds[item.id];}).length;
    selectAll.checked=!!pickupRecordState.rows.length&&pageSelected===pickupRecordState.rows.length;
    selectAll.indeterminate=pageSelected>0&&pageSelected<pickupRecordState.rows.length;
  }
  async function loadPickupRecords(){
    var summary=E('pickupRecordSummary');
    if(summary)summary.textContent='正在读取记录...';
    try{
      var query='?page='+pickupRecordState.page+'&page_size='+pickupRecordState.pageSize+'&q='+encodeURIComponent(pickupRecordState.q);
      var data=await api('/api/pickup-links'+query,{timeout:30000});
      pickupRecordState.rows=data.records||[];
      pickupRecordState.total=data.total||0;
      pickupRecordState.pages=data.pages||1;
      pickupRecordState.page=data.page||1;
      pickupRecordState.loaded=true;
      renderPickupRecords();
    }catch(error){
      pickupRecordState.rows=[];
      if(summary)summary.textContent=error.message||'读取生成记录失败';
      if(E('pickupRecordList'))E('pickupRecordList').innerHTML='';
    }
  }
  window.searchPickupRecords=function(){
    pickupRecordState.q=(E('pickupRecordSearch')&&E('pickupRecordSearch').value||'').trim().toLowerCase();
    pickupRecordState.page=1;
    loadPickupRecords();
  };
  window.changePickupRecordPage=function(delta){
    var next=Math.max(1,Math.min(pickupRecordState.pages,pickupRecordState.page+delta));
    if(next===pickupRecordState.page)return;
    pickupRecordState.page=next;
    loadPickupRecords();
  };
  window.setPickupRecordSelected=function(linkId,checked){
    if(checked)pickupRecordState.selectedIds[linkId]=true;
    else delete pickupRecordState.selectedIds[linkId];
    renderPickupRecords();
  };
  window.selectPickupRecordPage=function(checked){
    pickupRecordState.rows.forEach(function(item){
      if(checked)pickupRecordState.selectedIds[item.id]=true;
      else delete pickupRecordState.selectedIds[item.id];
    });
    renderPickupRecords();
  };
  window.closePickupRevokeModal=function(){
    var modal=E('pickupRevokeModal');
    if(modal)modal.remove();
  };
  window.requestRevokePickupLinks=function(linkIds){
    var ids=Array.isArray(linkIds)?linkIds:Object.keys(pickupRecordState.selectedIds);
    ids=ids.map(function(id){return String(id||'').trim();}).filter(Boolean);
    if(!ids.length)return;
    closePickupRevokeModal();
    var html='<div class="modal-overlay pickup-revoke-overlay" id="pickupRevokeModal" onclick="if(event.target===this)closePickupRevokeModal()"><div class="modal-box pickup-revoke-modal"><h3>让取码链接失效</h3><p>确认让 '+ids.length+' 条链接失效？旧链接将立即无法打开，邮箱本身和邮件不会被删除。</p><div class="modal-actions"><button type="button" class="btn btn-outline" onclick="closePickupRevokeModal()">取消</button><button type="button" class="btn btn-danger" id="pickupRevokeConfirm" onclick="revokePickupLinks('+ca(JSON.stringify(ids))+')">确认失效</button></div></div></div>';
    document.body.insertAdjacentHTML('beforeend',html);
  };
  window.revokePickupLinks=async function(linkIds){
    var button=E('pickupRevokeConfirm');
    if(button){button.disabled=true;button.textContent='处理中...';}
    var data=await api('/api/pickup-links/revoke-batch',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({link_ids:linkIds}),timeout:30000});
    if(!data.ok){
      if(button){button.disabled=false;button.textContent=data.error||'失效失败';}
      return;
    }
    linkIds.forEach(function(linkId){delete pickupRecordState.selectedIds[linkId];});
    closePickupRevokeModal();
    await loadPickupRecords();
    var summary=E('pickupRecordSummary');
    if(summary)summary.textContent='已让 '+(data.count||0)+' 条链接失效 · 当前有效 '+pickupRecordState.total+' 条';
  };
  window.copyPickupRecord=function(value){
    navigator.clipboard.writeText(value).then(function(){var el=E('pickupRecordSummary');if(el)el.textContent='邮箱和链接已复制';});
  };
  window.copyPickupRecordPage=function(){
    var value=pickupRecordState.rows.map(pickupRecordLine).join('\n');
    if(value)navigator.clipboard.writeText(value).then(function(){var el=E('pickupRecordSummary');if(el)el.textContent='本页记录已复制';});
  };
  window.generatePickupLinksBatch=async function(){
    var input=E('pickupBatchEmails');
    var countInput=E('pickupAliasCount');
    var button=E('pickupBatchGenerate');
    var statusEl=E('pickupBatchStatus');
    var value=input?input.value.trim():'';
    if(!value){if(statusEl){statusEl.className='pickup-batch-status err';statusEl.textContent='请填写邮箱地址';}return;}
    var perEmail=parseInt((countInput&&countInput.value)||'0',10);
    if(!Number.isInteger(perEmail)||perEmail<0||perEmail>100){if(statusEl){statusEl.className='pickup-batch-status err';statusEl.textContent='额外别名数量必须是 0 到 100';}if(countInput)countInput.focus();return;}
    var emailCount=value.split(/\r?\n/).map(function(line){return line.trim();}).filter(Boolean).length;
    button.disabled=true;
    button.textContent='生成中...';
    if(statusEl){statusEl.className='pickup-batch-status';statusEl.textContent=perEmail===0?'正在为 '+emailCount+' 个原邮箱生成取码链接...':'正在为 '+emailCount+' 个原邮箱及各自 '+perEmail+' 个 8 位随机别名生成取码链接...';}
    try{
      var data=await api('/api/pickup-links/batch',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({emails:value,random_tags:perEmail>0,per_email:perEmail}),timeout:120000});
      var rows=(data.results||[]).map(function(item){return item.email+'----'+location.origin+item.pickup_url;});
      var errors=(data.errors||[]).map(function(item){return item.email+'：'+item.error;});
      E('pickupBatchOutput').value=rows.join('\n');
      E('pickupBatchErrors').textContent=errors.length?'失败 '+errors.length+' 个：'+errors.join('；'):'';
      E('pickupBatchResult').hidden=false;
      E('pickupBatchCopy').hidden=!rows.length;
      E('pickupBatchDownload').hidden=!rows.length;
      pickupRecordState.loaded=false;
      statusEl.className='pickup-batch-status '+(rows.length?'ok':'err');
      statusEl.textContent='成功 '+rows.length+' 个，失败 '+errors.length+' 个';
      if(rows.length)window.dispatchEvent(new CustomEvent('pickup-links-updated'));
    }catch(error){
      statusEl.className='pickup-batch-status err';
      statusEl.textContent=error.message||'批量生成失败';
    }finally{
      button.disabled=false;
      button.textContent='生成链接';
    }
  };
  window.copyPickupBatchLinks=function(){
    var value=(E('pickupBatchOutput')||{}).value||'';
    if(!value)return;
    navigator.clipboard.writeText(value).then(function(){var el=E('pickupBatchStatus');if(el){el.className='pickup-batch-status ok';el.textContent='链接已复制';}});
  };
  window.downloadPickupBatchLinks=function(){
    var value=(E('pickupBatchOutput')||{}).value||'';
    if(!value)return;
    downloadPickupText(value,'邮箱取码链接-'+formatBeijingDateStamp(Date.now())+'.txt');
  };
  function downloadPickupText(value,filename){
    var blob=new Blob([value+'\n'],{type:'text/plain;charset=utf-8'});
    var url=URL.createObjectURL(blob);
    var link=document.createElement('a');
    link.href=url;
    link.download=filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  }
  window.downloadPickupRecordHistory=async function(){
    var button=E('pickupRecordDownload');
    button.disabled=true;
    button.textContent='准备中...';
    try{
      var data=await api('/api/pickup-links?page=1&page_size=5000&q='+encodeURIComponent(pickupRecordState.q),{timeout:30000});
      var value=(data.records||[]).map(pickupRecordLine).join('\n');
      if(value)downloadPickupText(value,'取码链接生成记录-'+formatBeijingDateStamp(Date.now())+'.txt');
    }catch(error){
      var summary=E('pickupRecordSummary');
      if(summary)summary.textContent=error.message||'下载记录失败';
    }finally{
      button.disabled=!pickupRecordState.total;
      button.textContent='下载记录';
    }
  };
  function rowHtml(item){
    var group=item.group||'unused';
    var disabled=item.lifecycle_status==='disabled';
    var viewEmail=item.pickup_email||item.email;
    var dot=item.status_type==='ok'?'ok':(item.status_type==='error'?'err':(item.status_type==='warn'?'warn':''));
    var account=item.icloud_email||item.account_email||item.account_name||item.account_id||'-';
    var groupLabel=disabled?'已停用':(groupNames[group]||group);
    var sub=disabled?'关联别名：'+(item.deactivation_alias||item.email):(item.unread?'未读':(item.status_message||''));
    var code=item.code?'<button class="code-value" onclick="copyCodeValue(&quot;'+ca(item.code||'')+'&quot;,&quot;'+ca(item.email)+'&quot;,this)" title="复制验证码">'+ce(item.code)+'</button>':'<span class="code-meta">-</span>';
    var preview=item.subject||item.preview||item.status_message?'<div class="code-preview" title="'+ca((item.subject||'')+' '+(item.preview||''))+'"><b>'+ce(item.subject||item.status_message||'')+'</b>'+(item.preview?'<span>'+ce(item.preview)+'</span>':'')+'</div>':'<span class="code-meta">暂无邮件</span>';
    var date=item.last_received_at?'<div class="code-meta" title="北京时间">'+ce(formatBeijingDateTime(item.last_received_at))+'</div>':'';
    var actions=disabled
      ? '<button onclick="copyCodeEmail(&quot;'+ca(viewEmail)+'&quot;)">复制邮箱</button><button class="danger" onclick="deleteDisabledAlias(&quot;'+ca(item.email)+'&quot;,&quot;'+ca(item.account_id||'')+'&quot;,&quot;'+ca(item.anonymousId||'')+'&quot;)">删除 iCloud</button>'
      : group==='trash'
      ? '<button onclick="copyCodeEmail(&quot;'+ca(viewEmail)+'&quot;)">复制邮箱</button><button onclick="moveCodeItem(&quot;'+ca(item.email)+'&quot;,&quot;unused&quot;)">恢复</button><button class="danger" onclick="purgeCodeItem(&quot;'+ca(item.email)+'&quot;)">清除</button>'
      : '<button onclick="copyCodeEmail(&quot;'+ca(viewEmail)+'&quot;)">复制邮箱</button><button '+(item.code?'':'disabled')+' onclick="copyCodeValue(&quot;'+ca(item.code||'')+'&quot;,&quot;'+ca(viewEmail)+'&quot;,this)">复制码</button><button class="danger" onclick="moveCodeItem(&quot;'+ca(item.email)+'&quot;,&quot;trash&quot;)">删除</button><button class="code-more-btn" title="更多操作" aria-label="更多操作" onclick="event.stopPropagation();openCodeActionMenu(&quot;'+ca(item.email)+'&quot;,this,&quot;'+ca(viewEmail)+'&quot;)">'+codeMoreIcon+'</button>';
    return '<div class="code-row code-item '+group+(disabled?' disabled':'')+(item.unread?' unread':'')+'" data-email="'+ca(item.email)+'"><div class="code-status-cell"><span class="code-dot '+dot+'"></span><div><div class="code-state-name">'+ce(groupLabel)+'</div><div class="code-state-sub" title="'+ca(sub||'')+'">'+ce(sub||'')+'</div></div></div><div><div class="code-email" title="'+ca(viewEmail)+'"><button class="code-email-link" onclick="openCodeInbox(&quot;'+ca(viewEmail)+'&quot;,&quot;'+ca(item.account_id||'')+'&quot;)" title="打开这个邮箱的收件箱">'+ce(viewEmail)+'</button></div><div class="code-meta" title="'+ca(account)+'">'+ce(account)+'</div></div><div>'+code+'</div><div class="code-label" title="'+ca(item.label||'')+'">'+ce(item.label||'-')+'</div><div><input class="code-remark" value="'+ca(item.remark||'')+'" placeholder="备注" onchange="saveCodeRemark(&quot;'+ca(item.email)+'&quot;,this.value)"></div><div>'+preview+date+'</div><div class="code-actions">'+actions+'</div></div>';
  }
  window.handleCodeAction=async function(email,action){
    closeCodeActionMenu();
    if(!action)return;
    if(action==='pickup-link'){await openPickupLink(email);return;}
    if(action==='read'){await markCodeRead(email);return;}
    if(action==='finished'){await moveCodeItem(email,'finished');return;}
    if(action==='unused'){await moveCodeItem(email,'unused');}
  };
  function showCodeCopyTip(anchor,text){
    var old=E('codeCopyTip');
    if(old)old.remove();
    if(!anchor){status(text||'已复制验证码',false);return;}
    var tip=document.createElement('div');
    tip.id='codeCopyTip';
    tip.className='code-copy-tip';
    tip.textContent=text||'已复制';
    document.body.appendChild(tip);
    var rect=anchor.getBoundingClientRect();
    var top=Math.max(8,rect.top-tip.offsetHeight-8);
    var left=Math.max(8,Math.min(rect.left+rect.width/2-tip.offsetWidth/2,window.innerWidth-tip.offsetWidth-8));
    tip.style.top=top+'px';
    tip.style.left=left+'px';
    requestAnimationFrame(function(){tip.classList.add('show');});
    setTimeout(function(){if(tip&&tip.parentNode)tip.remove();},1100);
  }
  window.copyCodeEmail=function(email){navigator.clipboard.writeText(email).then(function(){status('已复制邮箱 '+email,false);});};
  window.copyCodeValue=function(code,email,anchor){
    if(!code)return;
    if(anchor&&anchor.classList&&!anchor.classList.contains('code-value')){
      var row=anchor.closest('.code-item');
      var codeBtn=row&&row.querySelector('.code-value');
      if(codeBtn)anchor=codeBtn;
    }
    navigator.clipboard.writeText(code).then(function(){showCodeCopyTip(anchor,'已复制 '+code);markCodeRead(email);});
  };
  window.openCodeInbox=async function(email,accountId){
    if(!accountId){
      var found=(codeState.items||[]).find(function(x){return String(x.email||'').toLowerCase()===String(email||'').toLowerCase();});
      accountId=found&&found.account_id?found.account_id:'';
    }
    var nav=document.querySelector('.nav-item[data-tab="inbox"]');
    if(nav)nav.click();
    setTimeout(async function(){
      if(typeof updateInboxAccountSelect==='function')updateInboxAccountSelect();
      try{
        if(window._inboxSse){window._inboxSse.close();window._inboxSse=null;}
        window._inboxBusy=false;
      }catch(_){}
      var sel=E('inboxAccount');
      if(sel&&accountId&&Array.prototype.some.call(sel.options,function(o){return o.value===accountId;}))sel.value=accountId;
      var input=E('aliasSearchInput');
      if(input)input.value=email;
      var box=E('inboxMsgs');
      if(box)box.innerHTML='<div class="icloud-reader-empty">正在打开 '+ce(email)+' ...</div>';
      var accId=(sel&&sel.value)||accountId||'';
      if(!accId){if(box)box.innerHTML='<div class="empty"><div class="icon"></div>请先选择账号</div>';return;}
      var req=typeof apiSlow==='function'?apiSlow:api;
      var mailLimit=parseInt((E('inboxLimit')||{}).value||20)||20;
      var d=await req('/api/accounts/'+encodeURIComponent(accId)+'/mail/'+encodeURIComponent(email)+'?limit='+mailLimit+'&force=1',{timeout:120000});
      if(d.error){if(box)box.innerHTML='<div class="empty"><div class="icon"></div>'+ce(d.error)+'</div>';return;}
      if(typeof renderInboxMsgs==='function')renderInboxMsgs(d.emails||[],email+' ('+(d.count||0)+' 封)');
    },80);
  };
  window.moveCodeItem=async function(email,group){
    var d=await api('/api/inventory/'+encodeURIComponent(email)+'/move',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({group:group})});
    if(!d.ok){status(d.error||'操作失败',true);return;}
    await loadCodeDesk({force:true});
  };
  window.purgeCodeItem=async function(email){
    var d=await api('/api/inventory/'+encodeURIComponent(email)+'/purge',{method:'POST'});
    if(!d.ok){status(d.error||'清除失败',true);return;}
    await loadCodeDesk({force:true});
  };
  window.markCodeRead=async function(email){
    await api('/api/inventory/'+encodeURIComponent(email)+'/mark-read',{method:'POST'});
    var row=(codeState.items||[]).find(function(x){return x.email===email});
    if(row)row.unread=false;
    renderCodeDesk();
  };
  window.saveCodeRemark=async function(email,remark){
    var d=await api('/api/inventory/'+encodeURIComponent(email)+'/remark',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({remark:remark})});
    if(!d.ok){status(d.error||'备注保存失败',true);return;}
    var row=(codeState.items||[]).find(function(x){return x.email===email});
    if(row)row.remark=remark;
    status('备注已保存',false);
  };
  window.checkCodeIcloud=async function(){
    var limit=codeScanLimit()||200;
    status('正在检查 iCloud 收件箱...',false);
    var d=await api('/api/inventory/check-icloud',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({account_id:codeState.account_id,limit:limit,force:true}),timeout:120000});
    if(!d.ok){status((d.error||'查件失败')+(d.errors&&d.errors.length?' / '+d.errors[0]:''),true);return;}
    status('更新 '+(d.updated||0)+' 条收码记录'+(d.deactivated?'，识别停用 '+d.deactivated+' 个':''),false);
    await loadCodeDesk({force:true});
  };
  window.calibrateCodeCloud=async function(){
    var limit=codeScanLimit()||2000;
    var fetchBodies=Math.min(120,Math.max(10,limit));
    status('正在云端校准：扫描近 365 天云端邮件...',false);
    var d=await api('/api/inventory/calibrate-cloud',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({account_id:codeState.account_id,days:365,limit:limit,all_mailboxes:true,fetch_bodies:fetchBodies,limit_per_alias:12}),timeout:240000});
    if(!d.ok){status((d.error||'云端校准失败')+(d.errors&&d.errors.length?' / '+d.errors[0]:''),true);return;}
    status('校准完成：扫描 '+(d.scanned||0)+' 封，命中 '+(d.matched_aliases||0)+' 个地址，补正文 '+(d.body_fetched||0)+' 封',false);
    await loadCodeDesk({force:true});
  };
  window.checkCodeForward=async function(){
    var limit=codeScanLimit()||100;
    status('正在检查转发 IMAP...',false);
    var d=await api('/api/inventory/check-forward',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({limit:limit}),timeout:90000});
    if(!d.ok){status(d.error||'转发 IMAP 查件失败',true);return;}
    status('转发 IMAP 更新 '+(d.updated||0)+' 条'+(d.deactivated?'，识别停用 '+d.deactivated+' 个':''),false);
    await loadCodeDesk({force:true});
  };
  window.deleteDisabledAlias=async function(email,accountId,anonymousId){
    if(!accountId||!anonymousId){status('缺少 iCloud 别名身份，无法删除',true);return;}
    var modal=document.createElement('div');
    modal.className='modal-overlay';
    modal.innerHTML='<div class="modal-box alias-modal-danger"><h3>删除已停用隐私邮箱</h3><p>确认从 iCloud 删除这个已停用地址？删除通常不能恢复。</p><div class="alias-modal-summary"><strong>'+ce(email)+'</strong></div><div class="modal-actions"><button class="btn btn-outline" type="button">取消</button><button class="btn btn-danger" type="button">确认删除</button></div><div class="modal-msg"></div></div>';
    document.body.appendChild(modal);
    var actions=modal.querySelectorAll('.modal-actions button');
    actions[0].onclick=function(){modal.remove();};
    actions[1].onclick=async function(){
      actions[0].disabled=true;actions[1].disabled=true;actions[1].textContent='删除中...';
      try{
        var d=await api('/api/accounts/'+encodeURIComponent(accountId)+'/aliases/'+encodeURIComponent(anonymousId)+'/delete',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:email})});
        if(!d.ok)throw new Error(d.error||'删除失败');
        modal.remove();
        status('已从 iCloud 删除 '+email,false);
        await loadCodeDesk({force:true});
      }catch(error){
        var msg=modal.querySelector('.modal-msg');
        if(msg)msg.textContent=error.message||'删除失败';
        actions[0].disabled=false;actions[1].disabled=false;actions[1].textContent='确认删除';
      }
    };
  };
  window.exportCodeDesk=function(){window.open('/api/inventory/export?group='+encodeURIComponent(codeState.group||'all'),'_blank');};
  var _forwardProfiles=[];
  var _forwardEditingId='';
  var _forwardOauthTimer=null;
  var _forwardDeviceCode='';
  function forwardAccountName(accountId){
    var account=(accounts||[]).find(function(item){return String(item.id||'')===String(accountId||'');});
    return account?(account.icloud_email||account.real_email||account.name||account.id):'未绑定 iCloud 账号';
  }
  function forwardAccountOptions(selected){
    var h='<option value="">-- 选择 iCloud 账号 --</option>';
    (accounts||[]).forEach(function(account){
      var id=String(account.id||'');
      h+='<option value="'+ca(id)+'"'+(id===String(selected||'')?' selected':'')+'>'+ce(account.icloud_email||account.real_email||account.name||id)+'</option>';
    });
    return h;
  }
  function forwardProfileById(profileId){return _forwardProfiles.find(function(item){return item.id===profileId;})||null;}
  function renderForwardProfileList(){
    var list=E('forwardProfileList');
    if(!list)return;
    if(!_forwardProfiles.length){list.innerHTML='<div class="forward-empty">还没有转发邮箱绑定</div>';return;}
    list.innerHTML=_forwardProfiles.map(function(cfg){
      var provider=cfg.provider==='microsoft'?'Microsoft':'QQ';
      var auth=cfg.provider==='microsoft'?(cfg.has_refresh_token?'已授权':'待授权'):(cfg.has_password?'已配置':'待填写授权码');
      return '<div class="forward-profile-row'+(_forwardEditingId===cfg.id?' active':'')+'"><span class="status-dot '+(cfg.enabled?'online':'offline')+'"></span><div class="forward-profile-main"><strong>'+ce(forwardAccountName(cfg.account_id))+'</strong><span>'+provider+' · '+ce(cfg.username||'-')+' · '+auth+'</span></div><button class="btn btn-outline btn-sm" onclick="editForwardProfile(&quot;'+ca(cfg.id)+'&quot;)">编辑</button><button class="btn btn-danger btn-sm" onclick="requestDeleteForwardProfile(&quot;'+ca(cfg.id)+'&quot;)">删除</button></div>';
    }).join('');
  }
  function fillForwardEditor(cfg){
    cfg=cfg||{};
    _forwardEditingId=cfg.id||'';
    E('fwProfileId').value=_forwardEditingId;
    E('fwAccount').innerHTML=forwardAccountOptions(cfg.account_id||'');
    E('fwProvider').value=cfg.provider==='microsoft'?'microsoft':'qq';
    E('fwEnabled').checked=cfg.hasOwnProperty('enabled')?!!cfg.enabled:true;
    E('fwUser').value=cfg.username||'';
    E('fwPassword').value='';
    E('fwPassword').placeholder=cfg.has_password?'留空则保留现有授权码':'填写 QQ IMAP 授权码';
    E('fwMailbox').value=cfg.mailbox||'INBOX';
    E('fwClientId').value=cfg.client_id||'';
    E('fwTenant').value=cfg.tenant||'consumers';
    E('fwOauthState').textContent=cfg.provider==='microsoft'?(cfg.has_refresh_token?'OAuth2 已授权':'OAuth2 尚未授权'):'';
    toggleForwardProviderFields();
    renderForwardProfileList();
  }
  window.openForwardConfigModal=async function(){
    var d=await api('/api/forward-config');
    _forwardProfiles=(d&&d.configs)||[];
    var h='<div class="modal-overlay" id="forwardConfigModal" onclick="if(event.target===this)closeForwardConfigModal()"><div class="modal-box qq-imap-modal forward-imap-modal"><h3><i class="diamond"></i> 转发邮箱 IMAP</h3><div class="forward-modal-head"><span>iCloud 账号绑定</span><button class="btn btn-outline btn-sm" onclick="newForwardProfile()">新增绑定</button></div><div id="forwardProfileList" class="forward-profile-list"></div><div class="forward-editor"><input id="fwProfileId" type="hidden"><div class="forward-editor-grid"><label>iCloud 账号<select id="fwAccount"></select></label><label>邮箱服务<select id="fwProvider" onchange="toggleForwardProviderFields()"><option value="qq">QQ 邮箱</option><option value="microsoft">Microsoft / Outlook</option></select></label></div><label class="code-switch"><input id="fwEnabled" type="checkbox" checked><span>启用这条绑定</span></label><div class="qq-imap-server"><span>服务器</span><strong id="fwServer">imap.qq.com</strong><span>端口</span><strong>993 / SSL</strong></div><div class="qq-imap-fields"><label>收件邮箱<input id="fwUser" type="email" autocomplete="off"></label><label id="fwPasswordField">IMAP 授权码<input id="fwPassword" type="password" autocomplete="new-password"></label><label>扫描文件夹<input id="fwMailbox" placeholder="INBOX" value="INBOX"></label><div id="fwMicrosoftFields" class="forward-ms-fields"><label>应用客户端 ID<input id="fwClientId" autocomplete="off"></label><label>租户<input id="fwTenant" value="consumers" autocomplete="off"></label><div class="forward-oauth-row"><span id="fwOauthState"></span><button class="btn btn-outline btn-sm" id="btnMicrosoftAuth" onclick="startMicrosoftForwardAuth()">Microsoft 授权</button></div></div></div></div><div class="modal-actions"><button class="btn btn-outline" onclick="closeForwardConfigModal()">关闭</button><button class="btn btn-primary" id="btnSaveForward" onclick="saveForwardConfigModal()">保存并测试</button></div><div class="modal-msg" id="forwardConfigMsg"></div></div></div>';
    document.body.insertAdjacentHTML('beforeend',h);
    renderForwardProfileList();
    fillForwardEditor(_forwardProfiles[0]||{});
  };
  window.closeForwardConfigModal=function(){if(_forwardOauthTimer){clearInterval(_forwardOauthTimer);_forwardOauthTimer=null;}var m=E('forwardConfigModal');if(m)m.remove();};
  window.newForwardProfile=function(){fillForwardEditor({enabled:true,provider:'qq',mailbox:'INBOX'});};
  window.editForwardProfile=function(profileId){var cfg=forwardProfileById(profileId);if(cfg)fillForwardEditor(cfg);};
  window.toggleForwardProviderFields=function(){
    var microsoft=E('fwProvider')&&E('fwProvider').value==='microsoft';
    if(E('fwServer'))E('fwServer').textContent=microsoft?'outlook.office365.com':'imap.qq.com';
    if(E('fwPasswordField'))E('fwPasswordField').style.display=microsoft?'none':'grid';
    if(E('fwMicrosoftFields'))E('fwMicrosoftFields').style.display=microsoft?'grid':'none';
    if(E('btnSaveForward'))E('btnSaveForward').textContent=microsoft?'保存配置':'保存并测试';
  };
  async function reloadForwardProfiles(preferredId){
    var latest=await api('/api/forward-config');
    _forwardProfiles=(latest&&latest.configs)||[];
    renderForwardProfileList();
    var cfg=forwardProfileById(preferredId||_forwardEditingId);
    if(cfg)fillForwardEditor(cfg);
  }
  window.saveForwardConfigModal=async function(){
    var username=E('fwUser').value.trim().toLowerCase();
    var enabled=E('fwEnabled').checked;
    var provider=E('fwProvider').value;
    var accountId=E('fwAccount').value;
    var msg=E('forwardConfigMsg');
    if(!accountId){msg.innerHTML='<span style="color:var(--red)">请选择对应的 iCloud 账号</span>';return null;}
    if(enabled&&provider==='qq'&&!/@(qq\.com|foxmail\.com)$/i.test(username)){msg.innerHTML='<span style="color:var(--red)">请填写完整的 QQ 邮箱地址</span>';return null;}
    if(enabled&&provider==='microsoft'&&!username){msg.innerHTML='<span style="color:var(--red)">请填写 Microsoft 邮箱</span>';return null;}
    if(provider==='microsoft'&&!E('fwClientId').value.trim()){msg.innerHTML='<span style="color:var(--red)">请填写 Azure 应用客户端 ID</span>';return null;}
    var btn=E('btnSaveForward');
    if(btn){btn.disabled=true;btn.textContent='连接中...';}
    var old=forwardProfileById(_forwardEditingId)||{};
    var body={id:_forwardEditingId,account_id:accountId,enabled:enabled,provider:provider,username:username,password:E('fwPassword').value,mailbox:E('fwMailbox').value.trim()||'INBOX',client_id:E('fwClientId').value.trim(),tenant:E('fwTenant').value.trim()||'consumers',test:enabled&&(provider==='qq'||!!old.has_refresh_token)};
    var d=await api('/api/forward-config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    if(btn){btn.disabled=false;toggleForwardProviderFields();}
    if(!d.ok){msg.innerHTML='<span style="color:var(--red)">'+ce((d.saved?'已保存，但连接失败：':'')+(d.error||'保存失败'))+'</span>';return d;}
    _forwardEditingId=(d.config&&d.config.id)||_forwardEditingId;
    msg.innerHTML=provider==='microsoft'&&!old.has_refresh_token?'<span style="color:var(--green)">配置已保存，请继续完成 Microsoft 授权</span>':'<span style="color:var(--green)">IMAP 连接成功，收件箱 '+ce((d.test&&d.test.message_count)||0)+' 封</span>';
    await reloadForwardProfiles(_forwardEditingId);
    return d;
  };
  window.requestDeleteForwardProfile=function(profileId){
    var cfg=forwardProfileById(profileId);var msg=E('forwardConfigMsg');if(!cfg||!msg)return;
    msg.innerHTML='<span style="color:var(--red)">删除 '+ce(forwardAccountName(cfg.account_id))+' 的 '+(cfg.provider==='microsoft'?'Microsoft':'QQ')+' 绑定？</span> <button class="btn btn-danger btn-sm" onclick="confirmDeleteForwardProfile(&quot;'+ca(profileId)+'&quot;)">确认删除</button>';
  };
  window.confirmDeleteForwardProfile=async function(profileId){
    var d=await api('/api/forward-config/'+encodeURIComponent(profileId),{method:'DELETE'});
    if(!d.ok){E('forwardConfigMsg').innerHTML='<span style="color:var(--red)">'+ce(d.error||'删除失败')+'</span>';return;}
    _forwardEditingId='';await reloadForwardProfiles('');fillForwardEditor(_forwardProfiles[0]||{enabled:true,provider:'qq',mailbox:'INBOX'});
    E('forwardConfigMsg').innerHTML='<span style="color:var(--green)">绑定已删除</span>';
  };
  window.startMicrosoftForwardAuth=async function(){
    var saved=await saveForwardConfigModal();
    if(!saved||!saved.ok)return;
    var profileId=(saved.config&&saved.config.id)||_forwardEditingId;
    var d=await api('/api/forward-config/'+encodeURIComponent(profileId)+'/microsoft/start',{method:'POST'});
    var msg=E('forwardConfigMsg');
    if(!d.ok){msg.innerHTML='<span style="color:var(--red)">'+ce(d.error||'授权启动失败')+'</span>';return;}
    _forwardDeviceCode=d.device_code||'';
    var authUrl=d.verification_uri_complete||d.verification_uri||'';
    msg.innerHTML='<div class="forward-device-code"><span>授权码</span><strong>'+ce(d.user_code||'')+'</strong><a class="btn btn-primary btn-sm" href="'+ca(authUrl)+'" target="_blank" rel="noopener">打开 Microsoft 授权</a><small>等待授权完成...</small></div>';
    if(_forwardOauthTimer)clearInterval(_forwardOauthTimer);
    var polling=false;
    _forwardOauthTimer=setInterval(async function(){
      if(polling||!E('forwardConfigModal'))return;polling=true;
      try{
        var result=await api('/api/forward-config/'+encodeURIComponent(profileId)+'/microsoft/poll',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({device_code:_forwardDeviceCode})});
        if(result.authorized){
          clearInterval(_forwardOauthTimer);_forwardOauthTimer=null;
          var verified=await api('/api/forward-config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:profileId,test:true})});
          await reloadForwardProfiles(profileId);
          E('forwardConfigMsg').innerHTML=verified.ok?'<span style="color:var(--green)">Microsoft OAuth2 授权并连接成功，收件箱 '+ce((verified.test&&verified.test.message_count)||0)+' 封</span>':'<span style="color:var(--red)">授权完成，但 IMAP 测试失败：'+ce(verified.error||'未知错误')+'</span>';
        }
        else if(!result.ok){clearInterval(_forwardOauthTimer);_forwardOauthTimer=null;E('forwardConfigMsg').innerHTML='<span style="color:var(--red)">'+ce(result.error||'授权失败')+'</span>';}
      }finally{polling=false;}
    },Math.max(5,parseInt(d.interval)||5)*1000);
  };
  window.openAutoStockModal=async function(){
    if(curTab!=='batch'){
      var nav=document.querySelector('.nav-item[data-tab="batch"]');
      if(nav)nav.click();
    }
    setTimeout(function(){
      if(typeof renderBatchPanel==='function')renderBatchPanel();
      var slot=E('batchAutoStockSlot');
      if(slot)slot.scrollIntoView({block:'center',behavior:'smooth'});
      var target=E('stockTarget');
      if(target)target.focus();
    },60);
  };
  window.closeAutoStockModal=function(){var m=E('autoStockModal');if(m)m.remove();};
  function stockBody(){
    var body=autoStockFormConfig();
    if(body.all_accounts)body.account_ids=[];
    return body;
  }
  function validateStockBody(body){
    if(!body.all_accounts&&!body.account_ids.length){
      var msg=E('autoStockMsg');
      if(msg){msg.className='batch-auto-msg err';msg.textContent='请至少勾选一个账号';}
      return false;
    }
    return true;
  }
  window.saveAutoStockModal=async function(){
    var body=stockBody();
    if(!validateStockBody(body))return;
    var msg=E('autoStockMsg');
    if(msg){msg.className='batch-auto-msg';msg.textContent='保存中...';}
    var d=await api('/api/auto-stock',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    msg=E('autoStockMsg');
    if(msg){msg.className='batch-auto-msg '+(d.ok?'ok':'err');msg.textContent=d.ok?'已保存':(d.error||'保存失败');}
    if(d.ok){autoStockConfigCache=d.config||body;refreshBatchAutoStockText('已保存',false);}
  };
  window.runAutoStockNow=async function(){
    var body=stockBody();
    if(!validateStockBody(body))return;
    var msg=E('autoStockMsg');
    if(msg){msg.className='batch-auto-msg';msg.textContent='正在补货...';}
    var saved=await api('/api/auto-stock',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    if(!saved.ok){
      msg=E('autoStockMsg');
      if(msg){msg.className='batch-auto-msg err';msg.textContent=saved.error||'保存失败';}
      return;
    }
    autoStockConfigCache=saved.config||body;
    var d=await api('/api/auto-stock/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),timeout:90000});
    msg=E('autoStockMsg');
    if(msg){msg.className='batch-auto-msg '+(d.ok?'ok':'err');msg.textContent=d.ok?(d.message||('已创建 '+(d.created||0)+' 个')):(d.error||'补货失败');}
    if(d.ok){refreshBatchAutoStockText('已创建 '+(d.created||0)+' 个',false);await loadCodeDesk({force:true});}
  };
  var oldRefreshAll=window.refreshAll;
  if(typeof oldRefreshAll==='function'){
    window.refreshAll=async function(){
      var opts=arguments[0]||{};
      await oldRefreshAll.apply(this,arguments);
      if(curTab==='codes'&&!opts.background)loadCodeDesk({force:true});
    };
  }
  window.codeState=codeState;
  install();
})();
