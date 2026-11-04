/* Apple-style admin enhancements and inbox runtime. */
(function(){
  function cleanCookieValue(value){
    var text=String(value==null?'':value).trim();
    if(text.length>=2){
      var first=text.charAt(0);
      var last=text.charAt(text.length-1);
      if((first==='"'&&last==='"')||(first==="'"&&last==="'")){
        text=text.slice(1,-1);
      }
    }
    return text;
  }
  function normalizeCookieHeader(raw){
    raw=String(raw||'').trim();
    if(!raw)return '';
    raw=raw.replace(/^\s*cookie\s*:\s*/i,'').trim();
    if(raw.charAt(0)==='{'){
      try{
        var obj=JSON.parse(raw);
        Object.keys(obj).forEach(function(k){
          if(obj[k]!=null)obj[k]=cleanCookieValue(obj[k]);
        });
        return JSON.stringify(obj);
      }catch(_){}
    }
    var parts=raw.split(';');
    var out=[];
    parts.forEach(function(part){
      var item=part.trim();
      if(!item)return;
      var idx=item.indexOf('=');
      if(idx<0)return;
      var name=item.slice(0,idx).trim();
      var value=cleanCookieValue(item.slice(idx+1));
      if(name)out.push(name+'='+value);
    });
    return out.length?out.join('; '):raw;
  }
  window.normalizeCookieHeader=normalizeCookieHeader;
  function bindCookieInputNormalizer(){
    var input=E('cookieInput');
    if(!input||input.dataset.cookieNormalizeBound)return;
    input.dataset.cookieNormalizeBound='1';
    var run=function(){
      var before=String(input.value||'').trim();
      var after=normalizeCookieHeader(before);
      if(after&&after!==before)input.value=after;
    };
    input.addEventListener('paste',function(){setTimeout(run,0);});
    input.addEventListener('blur',run);
  }
  window.bindCookieInputNormalizer=bindCookieInputNormalizer;
  window.showAddAccountModal = function(){
    var h=[
      '<div class="modal-overlay" id="addAccModal">',
      '<div class="modal-box account-modal">',
      '<h3><i class="diamond"></i> 导入 iCloud Cookie</h3>',
      '<p>推荐安装 Cookie 助手。你在本机 Chrome 登录 iCloud 后，点扩展生成 Cookie，再复制粘贴到下面输入框。</p>',
      '<div class="modal-note">',
      '<strong>Cookie 助手</strong>',
      '<span>下载 zip 后解压，在 Chrome 扩展程序页面加载已解压的扩展。登录 iCloud 后生成 Cookie，再粘贴到下方。</span>',
      '<div class="modal-button-row">',
      '<button type="button" class="btn btn-primary" onclick="downloadCookieHelper()">安装 Cookie 助手</button>',
      '<button type="button" class="btn btn-outline" onclick="window.open(&quot;https://www.icloud.com.cn/&quot;,&quot;_blank&quot;)">打开 iCloud</button>',
      '</div>',
      '</div>',
      '<div class="modal-form">',
      '<label><span>账号名称</span><input type="text" id="accNameInput" placeholder="例如：主号"></label>',
      '<label><span>iCloud 地区</span><select id="hostInput"><option value="icloud.com.cn" selected>中国区 iCloud (icloud.com.cn)</option><option value="icloud.com">全球区 iCloud (icloud.com)</option></select></label>',
      '<div class="modal-form-grid">',
      '<label><span>iCloud 邮箱</span><input type="text" id="addIcloudEmailInput" placeholder="用于收件/取码，可选"></label>',
      '<label><span>App 专用密码</span><input type="password" id="addAppPwdInput" placeholder="可选" autocomplete="new-password"></label>',
      '</div>',
      '<div class="modal-help">App 专用密码只用于 IMAP 收件/取码，不是 Apple ID 登录密码。</div>',
      '<div class="modal-button-row"><button type="button" class="btn btn-outline" onclick="window.open(&quot;https://account.apple.com/account/manage/section/security&quot;,&quot;_blank&quot;)">打开 Apple ID 获取密码</button></div>',
      '<label><span>Cookie</span><textarea id="cookieInput" rows="6" placeholder="粘贴 Cookie Header String：name=value; name2=value2; ..."></textarea></label>',
      '</div>',
      '<div class="modal-msg" id="addAccMsg"></div>',
      '<div class="modal-actions"><button type="button" class="btn btn-outline" onclick="closeModal(&quot;addAccModal&quot;)">取消</button><button type="button" class="btn btn-primary" id="btnAddAccount" onclick="addAccount()">手动添加并校验</button></div>',
      '</div></div>'
    ].join('');
    closeModal('addAccModal');
    document.body.insertAdjacentHTML('beforeend',h);
    bindCookieInputNormalizer();
  };
  window.downloadCookieHelper = function(){
    window.open('/api/cookie-helper/download','_blank');
    var msg=E('addAccMsg');
    if(msg)msg.innerHTML='<span style="color:var(--ink-soft)">已开始下载。解压后在 Chrome 扩展程序页面加载文件夹；浏览器不允许网页直接打开 chrome://extensions/，请手动打开。</span>';
  };
  function normalizeAliasRow(a){
    var acc=accounts.find(function(x){return x.id===a.account_id});
    var created=a.createdAt||a.created_at||0;
    return {
      email:a.email||'',
      account_id:a.account_id||'',
      account_name:a.account_name||(acc?(acc.name||acc.real_email||''):''),
      account_email:a.account_email||(acc?(acc.real_email||''):''),
      icloud_email:a.icloud_email||(acc?(acc.icloud_email||''):''),
      label:a.label||'',
      active:a.active,
      anonymousId:a.anonymousId||a.anonymous_id||'',
      createdAt:created||0,
      created_at:a.created_at||created||'',
      lifecycle_status:a.lifecycle_status||'active',
      lifecycle_reason:a.lifecycle_reason||'',
      deactivated_at:a.deactivated_at||'',
      deactivation_alias:a.deactivation_alias||'',
      deactivation_subject:a.deactivation_subject||'',
      deactivation_sender:a.deactivation_sender||'',
      deactivation_message_id:a.deactivation_message_id||'',
      deactivation_message_date:a.deactivation_message_date||'',
      deactivation_source:a.deactivation_source||'',
      source:a.source||'cloud'
    };
  }
  function mergeEmailRows(cloudRows,localRows){
    var map={};
    (cloudRows||[]).forEach(function(a){
      var row=normalizeAliasRow(a);
      if(row.email)map[row.email]=row;
    });
    (localRows||[]).forEach(function(e){
      if(!e.email||map[e.email])return;
      var acc=accounts.find(function(a){return a.id===e.account_id});
      map[e.email]={
        email:e.email,
        account_id:e.account_id||'',
        account_name:e.account_name||(acc?(acc.name||acc.real_email||''):''),
        account_email:e.account_email||(acc?(acc.real_email||''):''),
        icloud_email:e.icloud_email||(acc?(acc.icloud_email||''):''),
        label:e.label||'',
        active:e.active,
        anonymousId:e.anonymousId||'',
        createdAt:e.createdAt||0,
        created_at:e.created_at||'',
        lifecycle_status:e.lifecycle_status||'active',
        lifecycle_reason:e.lifecycle_reason||'',
        deactivated_at:e.deactivated_at||'',
        deactivation_alias:e.deactivation_alias||'',
        deactivation_subject:e.deactivation_subject||'',
        deactivation_sender:e.deactivation_sender||'',
        deactivation_message_id:e.deactivation_message_id||'',
        deactivation_message_date:e.deactivation_message_date||'',
        deactivation_source:e.deactivation_source||'',
        source:'local'
      };
    });
    return Object.keys(map).map(function(k){return map[k]}).sort(function(a,b){
      var ad=parseAppDate(a.createdAt||a.created_at),bd=parseAppDate(b.createdAt||b.created_at);
      var av=ad?ad.getTime():0,bv=bd?bd.getTime():0;
      if(av||bv)return bv-av;
      return String(a.email).localeCompare(String(b.email));
    });
  }
  var _aliasSyncBusy=false;
  var _lastAliasSyncAt=0;
  var _aliasCacheLoaded=false;
  var _lastAliasSyncErrors=[];
  function setAliasSyncText(text){
    var el=E('emailCount');
    if(el)el.textContent=text;
  }
  function aliasToolbarStatus(text,isErr){
    var el=E('aliasActionStatus');
    if(!el){
      var count=E('emailCount');
      if(count){
        count.insertAdjacentHTML('afterend','<span id="aliasActionStatus" class="alias-toolbar-status"></span>');
        el=E('aliasActionStatus');
      }
    }
    if(!el)return;
    el.textContent=text||'';
    el.className='alias-toolbar-status '+(isErr?'err':'');
  }
  function mergeWithCurrentCloud(localRows){
    var cloudRows=emails.filter(function(e){return e.source==='cloud'||e.anonymousId;});
    emails=mergeEmailRows(cloudRows,localRows||[]);
  }
  async function loadAliasCache(){
    var d=await api('/api/aliases/cache');
    var cached=d.aliases||[];
    if(!cached.length)return false;
    var local=await api('/api/emails');
    emails=mergeEmailRows(cached,local.emails||[]);
    _aliasCacheLoaded=true;
    E('emailCount').textContent=emails.length;
    updateEmailFilter();
    if(curTab==='emails')renderAliasTable();
    return true;
  }
  async function syncCloudAliases(opts){
    opts=opts||{};
    if(_aliasSyncBusy&&opts.waitForBusy){
      var waitDeadline=Date.now()+30000;
      while(_aliasSyncBusy&&Date.now()<waitDeadline){
        await new Promise(function(resolve){setTimeout(resolve,120);});
      }
    }
    if(_aliasSyncBusy)return false;
    _aliasSyncBusy=true;
    _lastAliasSyncErrors=[];
    var box=E('aliasTableContainer');
    var hadRows=emails.length>0;
    if(opts.showLoading&&!hadRows&&box){
      box.innerHTML='<div class="empty"><div class="icon"></div>正在从 iCloud 云端同步...</div>';
    }else if(!opts.quiet){
      setAliasSyncText('同步中...');
    }
    try{
      var accountFilter=E('aliasFilter')?E('aliasFilter').value:'all';
      var selectedAccountId=accountFilter&&accountFilter!=='all'?accountFilter:'';
      if(opts.allAccounts)selectedAccountId='';
      var path='/api/aliases'+(selectedAccountId?'?account_id='+encodeURIComponent(selectedAccountId):'');
      var d=await apiSlow(path);
      _lastAliasSyncErrors=(d.errors||[]).slice();
      _lastAliasSyncAt=Date.now();
      if(d.error&&!d.ok){
        if(!hadRows&&box)box.innerHTML='<div class="empty"><div class="icon"></div>'+esc(d.error||'云端同步失败')+'</div>';
        aliasToolbarStatus('云端同步失败: '+(d.error||'?'),true);
        return false;
      }
      var local=await api('/api/emails');
      emails=mergeEmailRows(d.aliases||[],local.emails||[]);
      _aliasCacheLoaded=true;
      E('emailCount').textContent=emails.length;
      updateEmailFilter();
      if(curTab==='emails')renderAliasTable();
      var synced=Number(d.synced_count==null?(d.aliases||[]).length:d.synced_count);
      var selected=selectedAccountId?(accounts||[]).find(function(account){return String(account.id||'')===selectedAccountId;}):null;
      var targetName=selected?(selected.name||selected.real_email||selected.icloud_email||selectedAccountId):'全部账号';
      var failures=(d.errors||[]).map(function(item){return (item.account||item.account_id||'账号')+': '+(item.error||'同步失败');});
      aliasToolbarStatus(targetName+' 已同步 '+synced+' 个云端别名'+(failures.length?'；失败 '+failures.join('；'):''),failures.length>0);
      return true;
    }finally{
      _aliasSyncBusy=false;
    }
  }
  window.refreshEmails = async function(opts){
    opts=opts||{};
    if(opts.force){
      await syncCloudAliases({showLoading:!emails.length,toast:false,quiet:true});
      return;
    }
    var hadRows=emails.length>0;
    var hasCache=await loadAliasCache();
    if(!hasCache&&hadRows){
      if(curTab==='emails')renderAliasTable();
      return;
    }
    if(!hasCache){
      var local=await api('/api/emails');
      emails=mergeEmailRows([],local.emails||[]);
      updateEmailFilter();
      if(emails.length){
        if(curTab==='emails')renderAliasTable();
        aliasToolbarStatus('显示本地记录，点“云端同步”刷新 iCloud',false);
        return;
      }
      var box=E('aliasTableContainer');
      if(box)box.innerHTML='<div class="empty"><div class="icon"></div>暂无本地记录。点“云端同步”从 iCloud 拉取当前别名。</div>';
      return;
    }
    if(curTab==='emails'){
      renderAliasTable();
    }
  };
  window.refreshAliases = async function(){
    aliasToolbarStatus('正在同步...');
    await syncCloudAliases({showLoading:true,toast:false});
  };
  window.updateEmailFilter = function(){
    var sel=E('aliasFilter');
    if(!sel)return;
    var old=sel.value||'all';
    var counts={all:emails.length};
    emails.forEach(function(e){if(e.account_id)counts[e.account_id]=(counts[e.account_id]||0)+1;});
    var h='<option value="all">全部账号 ('+emails.length+')</option>';
    accounts.forEach(function(a){
      var count=counts[a.id]||0;
      h+='<option value="'+escAttr(a.id)+'">'+esc(a.name||a.real_email||a.id)+' ('+count+')</option>';
    });
    sel.innerHTML=h;
    sel.value=counts.hasOwnProperty(old)?old:'all';
  };
  function aliasByEmail(email){
    email=String(email||'').toLowerCase();
    return emails.find(function(e){return String(e.email||'').toLowerCase()===email;});
  }
  var _aliasRowMessages={};
  function aliasMsgKey(email){
    return String(email||'').toLowerCase();
  }
  function aliasRowMessageHtml(email){
    var item=_aliasRowMessages[aliasMsgKey(email)];
    if(!item)return '<div class="alias-row-message"></div>';
    return '<div class="alias-row-message '+(item.err?'err':'')+'">'+esc(item.text||'')+'</div>';
  }
  function setAliasRowMessage(email,text,isErr){
    if(!email)return;
    _aliasRowMessages[aliasMsgKey(email)]={text:text,err:!!isErr};
    if(curTab==='emails')renderAliasTable();
  }
  function clearAliasRowMessage(email){
    delete _aliasRowMessages[aliasMsgKey(email)];
  }
  var _aliasSelection={};
  var _aliasPage=1;
  var _aliasPageSize=20;
  var _aliasFilterValue='';
  var _aliasSearchValue='';
  var _aliasBatchQueries=[];
  function aliasPageSize(){
    var el=E('aliasPageSize');
    var n=parseInt((el&&el.value)||_aliasPageSize||20);
    return [10,20,50,100].indexOf(n)>=0?n:20;
  }
  function ensureAliasControls(){
    var bar=document.querySelector('#view-emails .filter-bar');
    if(!bar)return;
    if(!E('aliasPageSize')){
      bar.insertAdjacentHTML('beforeend','<span class="alias-control-label">每页:</span><select id="aliasPageSize" onchange="setAliasPageSize(this.value)" title="每页显示邮箱数量"><option value="10">10</option><option value="20" selected>20</option><option value="50">50</option><option value="100">100</option></select>');
    }
    if(!E('aliasPagerInline')){
      var size=E('aliasPageSize');
      if(size)size.insertAdjacentHTML('afterend','<span id="aliasPagerInline" class="alias-list-pager"></span>');
    }
    if(!E('aliasBatchSearchState')){
      var search=E('aliasListSearch');
      if(search)search.insertAdjacentHTML('afterend','<span id="aliasBatchSearchState" class="alias-batch-search-state"></span>');
    }
  }
  window.setAliasPageSize=function(value){
    _aliasPageSize=parseInt(value)||20;
    _aliasPage=1;
    renderAliasTable();
  };
  window.setAliasPage=function(page){
    _aliasPage=Math.max(1,parseInt(page)||1);
    renderAliasTable();
  };
  window.setAliasListSearch=function(value){
    _aliasSearchValue=String(value||'').trim().toLowerCase();
    if(_aliasSearchValue.length)_aliasBatchQueries=[];
    _aliasPage=1;
    renderAliasTable();
  };
  function parseAliasBatchQueries(value){
    var matches=String(value||'').toLowerCase().match(/[a-z0-9.!#$%&'*+\/=?^_`{|}~-]+@[a-z0-9.-]+\.[a-z]{2,}/g)||[];
    return Array.from(new Set(matches));
  }
  function baseAliasEmail(value){
    var email=String(value||'').trim().toLowerCase();
    var at=email.lastIndexOf('@');
    if(at<=0)return email;
    return email.slice(0,at).replace(/\+.*$/,'')+email.slice(at);
  }
  function renderAliasBatchSearchState(){
    var state=E('aliasBatchSearchState');
    if(!state)return;
    state.innerHTML=_aliasBatchQueries.length?'<span>批量筛选 '+_aliasBatchQueries.length+' 个</span><button type="button" onclick="clearAliasBatchSearch()" title="清除批量筛选">×</button>':'';
  }
  window.openAliasBatchSearch=function(){
    var initial=_aliasBatchQueries.join('\n');
    var h='<div class="modal-overlay" id="aliasBatchSearchModal" onclick="if(event.target===this)closeAliasBatchSearch()"><div class="modal-box alias-batch-search-modal"><h3><i class="diamond"></i> 批量查找隐私邮箱</h3><label>邮箱（支持 + 标签），每行一个<textarea id="aliasBatchSearchInput" spellcheck="false" placeholder="name1@icloud.com\nname2+tag@icloud.com">'+esc(initial)+'</textarea></label><div class="modal-actions"><button class="btn btn-outline" onclick="closeAliasBatchSearch()">取消</button><button class="btn btn-outline" onclick="applyAliasBatchSearch(false)">仅查找</button><button class="btn btn-primary" onclick="applyAliasBatchSearch(true)">查找并选中</button></div><div class="modal-msg" id="aliasBatchSearchMsg"></div></div></div>';
    document.body.insertAdjacentHTML('beforeend',h);
    setTimeout(function(){var input=E('aliasBatchSearchInput');if(input)input.focus();},0);
  };
  window.closeAliasBatchSearch=function(){var modal=E('aliasBatchSearchModal');if(modal)modal.remove();};
  window.applyAliasBatchSearch=async function(selectMatches){
    var queries=parseAliasBatchQueries((E('aliasBatchSearchInput')||{}).value||'');
    var msg=E('aliasBatchSearchMsg');
    if(!queries.length){if(msg)msg.innerHTML='<span style="color:var(--red)">没有识别到邮箱地址</span>';return;}
    var bases=Array.from(new Set(queries.map(baseAliasEmail)));
    var modal=E('aliasBatchSearchModal');
    var buttons=modal?modal.querySelectorAll('.modal-actions button'):[];
    buttons.forEach(function(button){button.disabled=true;});
    if(msg)msg.textContent='正在跨全部账号同步并查找 '+bases.length+' 个隐私邮箱...';
    try{
      var syncOk=await syncCloudAliases({showLoading:false,toast:false,quiet:true,allAccounts:true,waitForBusy:true});
      var accountFilter=E('aliasFilter');
      if(accountFilter)accountFilter.value='all';
      _aliasBatchQueries=bases;
      _aliasSearchValue='';
      if(E('aliasListSearch'))E('aliasListSearch').value='';
      _aliasPage=1;
      var matches=visibleAliasRows();
      if(selectMatches){
        _aliasSelection={};
        matches.forEach(function(row){_aliasSelection[aliasRowKey(row)]=true;});
      }
      renderAliasTable();
      closeAliasBatchSearch();
      var status='批量查找：输入 '+queries.length+' 个，换算 '+bases.length+' 个隐私邮箱，命中 '+matches.length;
      if(_lastAliasSyncErrors.length)status+='；'+_lastAliasSyncErrors.length+' 个账号同步失败';
      if(!syncOk)status+='；使用当前缓存';
      if(selectMatches)status+='，已选中';
      aliasToolbarStatus(status,matches.length===0||!syncOk||_lastAliasSyncErrors.length>0);
    }catch(error){
      if(msg)msg.innerHTML='<span style="color:var(--red)">'+esc(error.message||'批量查找失败')+'</span>';
      buttons.forEach(function(button){button.disabled=false;});
    }
  };
  window.clearAliasBatchSearch=function(){
    _aliasBatchQueries=[];
    _aliasPage=1;
    renderAliasTable();
  };
  function pagedAliasRows(list){
    var size=aliasPageSize();
    var pages=Math.max(1,Math.ceil((list||[]).length/size));
    if(_aliasPage>pages)_aliasPage=pages;
    var start=(_aliasPage-1)*size;
    return (list||[]).slice(start,start+size);
  }
  function aliasPagerHtml(total){
    var size=aliasPageSize();
    var pages=Math.max(1,Math.ceil(total/size));
    if(_aliasPage>pages)_aliasPage=pages;
    var from=total?((_aliasPage-1)*size+1):0;
    var to=Math.min(total,_aliasPage*size);
    return '<span>第 '+_aliasPage+' / '+pages+' 页 · '+from+'-'+to+' / '+total+'</span><button '+(_aliasPage<=1?'disabled':'')+' onclick="setAliasPage('+(_aliasPage-1)+')">上一页</button><button '+(_aliasPage>=pages?'disabled':'')+' onclick="setAliasPage('+(_aliasPage+1)+')">下一页</button>';
  }
  function updateAliasPager(total){
    ensureAliasControls();
    var p=E('aliasPagerInline');
    if(p)p.innerHTML=aliasPagerHtml(total||0);
  }
  function aliasRowKey(rowOrEmail){
    return aliasMsgKey(typeof rowOrEmail==='string'?rowOrEmail:(rowOrEmail&&rowOrEmail.email));
  }
  function visibleAliasRows(){
    var filter=E('aliasFilter')?E('aliasFilter').value:'all';
    if(filter!==_aliasFilterValue){
      _aliasFilterValue=filter;
      _aliasPage=1;
    }
    var list=filter==='all'?emails:emails.filter(function(e){return e.account_id===filter});
    if(_aliasBatchQueries.length){
      var wanted={};
      _aliasBatchQueries.forEach(function(email){wanted[baseAliasEmail(email)]=true;});
      list=list.filter(function(e){return !!wanted[baseAliasEmail(e.email)];});
    }
    var query=_aliasSearchValue;
    if(!query)return list;
    return list.filter(function(e){
      var acc=accounts.find(function(a){return a.id===e.account_id})||{};
      return [e.email,e.label,e.account_name,e.account_email,e.icloud_email,(e.pickup_link_emails||[]).join(' '),acc.name,acc.real_email,acc.icloud_email]
        .some(function(value){return String(value||'').toLowerCase().indexOf(query)>=0;});
    });
  }
  function pruneAliasSelection(list){
    var visible={};
    (list||[]).forEach(function(e){visible[aliasRowKey(e)]=1;});
    Object.keys(_aliasSelection).forEach(function(k){if(!visible[k])delete _aliasSelection[k];});
  }
  function selectedAliasRows(){
    var selected=_aliasSelection;
    return visibleAliasRows().filter(function(e){return !!selected[aliasRowKey(e)];});
  }
  function selectedAliasCount(){
    return selectedAliasRows().length;
  }
  function aliasIcloudAccount(row){
    var acc=accounts.find(function(a){return a.id===row.account_id});
    var val=(acc&&acc.icloud_email)||row.icloud_email||row.account_email||row.account_name||'';
    if(!/(icloud\.com|me\.com|mac\.com)/i.test(val||'')&&row.account_email&&/(icloud\.com|me\.com|mac\.com)/i.test(row.account_email)){
      val=row.account_email;
    }
    return val||row.account_email||row.account_id||'-';
  }
  function aliasBulkBarHtml(count){
    if(!count)return '<div class="alias-bulk-bar is-empty" aria-hidden="true"><strong>已选 0 个</strong><span class="alias-bulk-spacer"></span></div>';
    return '<div class="alias-bulk-bar"><strong>已选 '+count+' 个</strong><button onclick="createPickupLinksForSelected()">生成取码链接</button><button onclick="copySelectedAliases()">复制邮箱</button><button onclick="bulkEditAliasLabels()">批量改标签</button><button class="danger" onclick="bulkDeleteAliases()">批量删除</button><span class="alias-bulk-spacer"></span><button onclick="clearAliasSelection()">取消选择</button></div>';
  }
  function aliasHeadToolsHtml(count){
    if(!count)return '';
    return '<span class="alias-head-tools"><strong>已选 '+count+' 个</strong><button onclick="createPickupLinksForSelected()">生成取码链接</button><button onclick="copySelectedAliases()">复制邮箱</button><button onclick="bulkEditAliasLabels()">批量改标签</button><button class="danger" onclick="bulkDeleteAliases()">批量删除</button></span>';
  }
  function updateAliasSelectAllState(){
    var box=E('aliasSelectAll');
    if(!box)return;
    var list=pagedAliasRows(visibleAliasRows());
    var count=selectedAliasRows().length;
    var pageCount=list.filter(function(e){return !!_aliasSelection[aliasRowKey(e)];}).length;
    box.checked=!!list.length&&pageCount===list.length;
    box.indeterminate=pageCount>0&&pageCount<list.length;
  }
  window.toggleAliasSelection=function(email,checked){
    var key=aliasRowKey(email);
    if(checked)_aliasSelection[key]=true;
    else delete _aliasSelection[key];
    renderAliasTable();
  };
  function setAliasSelected(email,checked){
    var key=aliasRowKey(email);
    if(checked)_aliasSelection[key]=true;
    else delete _aliasSelection[key];
  }
  function aliasRowIndexByKey(key){
    var list=visibleAliasRows();
    for(var i=0;i<list.length;i++){
      if(aliasRowKey(list[i])===key)return i;
    }
    return -1;
  }
  function applyAliasDragRange(toEmail){
    if(!_aliasDragSelect.active)return;
    var list=visibleAliasRows();
    var toKey=aliasRowKey(toEmail);
    var start=_aliasDragSelect.startIndex;
    var end=aliasRowIndexByKey(toKey);
    if(start<0||end<0)return;
    var lo=Math.min(start,end),hi=Math.max(start,end);
    var next=Object.assign({},_aliasDragSelect.base);
    for(var i=lo;i<=hi;i++){
      var key=aliasRowKey(list[i]);
      if(_aliasDragSelect.value)next[key]=true;
      else delete next[key];
    }
    _aliasSelection=next;
    _aliasDragSelect.last=toKey;
    renderAliasTable();
  }
  var _aliasDragSelect={active:false,value:true,last:'',startKey:'',startIndex:-1,base:{}};
  var _aliasDragPending={active:false,email:'',x:0,y:0};
  function beginAliasDragSelect(email,base){
    var key=aliasRowKey(email);
    var next=!_aliasSelection[key];
    _aliasDragSelect={
      active:true,
      value:next,
      last:'',
      startKey:key,
      startIndex:aliasRowIndexByKey(key),
      base:base||Object.assign({},_aliasSelection)
    };
    document.body.classList.add('alias-dragging');
  }
  function activatePendingAliasDrag(toEmail){
    if(!_aliasDragPending.active)return false;
    var startEmail=_aliasDragPending.email;
    _aliasDragPending.active=false;
    beginAliasDragSelect(startEmail,Object.assign({},_aliasSelection));
    applyAliasDragRange(toEmail||startEmail);
    return true;
  }
  window.startAliasDragSelect=function(ev,email){
    if(ev&&ev.button!==0)return;
    if(ev){ev.preventDefault();ev.stopPropagation();}
    _aliasDragPending.active=false;
    beginAliasDragSelect(email);
    applyAliasDragRange(email);
  };
  window.enterAliasDragSelect=function(ev,email){
    if(!_aliasDragSelect.active)return;
    if(ev){ev.preventDefault();ev.stopPropagation();}
    var key=aliasRowKey(email);
    if(_aliasDragSelect.last===key)return;
    applyAliasDragRange(email);
  };
  function aliasDragIgnoredTarget(target){
    return !!(target&&target.closest&&target.closest('button,a,input,select,textarea,.alias-inline-actions'));
  }
  window.startAliasRowDragSelect=function(ev,email){
    if(ev&&ev.button!==0)return;
    if(aliasDragIgnoredTarget(ev&&ev.target))return;
    if(ev){ev.preventDefault();}
    _aliasDragPending={
      active:true,
      email:email,
      x:ev&&typeof ev.clientX==='number'?ev.clientX:0,
      y:ev&&typeof ev.clientY==='number'?ev.clientY:0
    };
  };
  window.enterAliasRowDragSelect=function(ev,email){
    if(_aliasDragSelect.active){
      window.enterAliasDragSelect(ev,email);
      return;
    }
    if(!_aliasDragPending.active)return;
    if(aliasRowKey(email)===aliasRowKey(_aliasDragPending.email))return;
    if(ev){ev.preventDefault();ev.stopPropagation();}
    activatePendingAliasDrag(email);
  };
  function stopAliasDragSelect(){
    _aliasDragPending.active=false;
    if(!_aliasDragSelect.active)return;
    _aliasDragSelect.active=false;
    _aliasDragSelect.base={};
    document.body.classList.remove('alias-dragging');
  }
  window.addEventListener('mousemove',function(ev){
    if(!_aliasDragPending.active||_aliasDragSelect.active)return;
    var dx=Math.abs((ev.clientX||0)-_aliasDragPending.x);
    var dy=Math.abs((ev.clientY||0)-_aliasDragPending.y);
    if(dx+dy<8)return;
    var el=document.elementFromPoint(ev.clientX,ev.clientY);
    var row=el&&el.closest?el.closest('.alias-row'):null;
    var email=row?row.getAttribute('data-email'):_aliasDragPending.email;
    if(email)activatePendingAliasDrag(email);
  },true);
  window.addEventListener('mouseup',stopAliasDragSelect,true);
  window.addEventListener('blur',stopAliasDragSelect,true);
  window.toggleAliasAll=function(checked){
    pagedAliasRows(visibleAliasRows()).forEach(function(row){
      var key=aliasRowKey(row);
      if(checked)_aliasSelection[key]=true;
      else delete _aliasSelection[key];
    });
    renderAliasTable();
  };
  window.clearAliasSelection=function(){
    _aliasSelection={};
    renderAliasTable();
  };
  async function resolveAliasForAction(row){
    if(row&&row.account_id&&row.anonymousId)return row;
    if(!row||!row.email)throw new Error('找不到这条邮箱记录');
    var ok=await syncCloudAliases({showLoading:false,toast:false});
    var latest=aliasByEmail(row.email);
    if(ok&&latest&&latest.account_id&&latest.anonymousId)return latest;
    if(latest)return latest;
    throw new Error('没有拿到 iCloud ID，请点“云端同步”后再试');
  }
  function closeAliasModal(){
    var m=E('aliasActionModal');
    if(m)m.remove();
  }
  window.closeAliasModal=closeAliasModal;
  window.editAliasLabel = function(idx){
    var row=emails[idx];
    if(!row)return;
    var h='<div class="modal-overlay" id="aliasActionModal" onclick="if(event.target===this)closeAliasModal()"><div class="modal-box"><h3><i class="diamond"></i> 修改标签</h3><p>标签会同步到 iCloud。保存失败时，当前列表不会被清空。</p><div class="alias-modal-summary"><strong>'+esc(row.email||'')+'</strong><span>账号: '+esc(row.account_email||row.account_name||row.account_id||'-')+'</span></div><label style="font-family:var(--mono);font-size:11px;color:var(--ink-faint);letter-spacing:.2em;text-transform:uppercase">标签</label><input type="text" id="aliasLabelInput" value="'+escAttr(row.label||'')+'" autocomplete="off"><div class="modal-actions"><button class="btn btn-outline" onclick="closeAliasModal()">取消</button><button class="btn btn-primary" id="btnAliasSave" onclick="saveAliasLabel('+idx+')">保存</button></div><div class="modal-msg" id="aliasModalMsg"></div></div></div>';
    document.body.insertAdjacentHTML('beforeend',h);
    setTimeout(function(){var input=E('aliasLabelInput');if(input){input.focus();input.select();}},0);
  };
  window.saveAliasLabel = async function(idx){
    var row=emails[idx];
    if(!row)return;
    var msg=E('aliasModalMsg');
    var btn=E('btnAliasSave');
    var label=String((E('aliasLabelInput')||{}).value||'').trim();
    if(btn){btn.disabled=true;btn.textContent='保存中...';}
    if(msg)msg.innerHTML='<span style="color:var(--ink-soft)">正在同步到 iCloud...</span>';
    try{
      row=await resolveAliasForAction(row);
      var d=await apiSlow('/api/accounts/'+encodeURIComponent(row.account_id)+'/aliases/'+encodeURIComponent(row.anonymousId||'_')+'/label',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({label:label,email:row.email||''})});
    if(d.ok){
      row.label=label;
      renderAliasTable();
        closeAliasModal();
      setAliasRowMessage(row.email,'标签已同步到 iCloud',false);
    }else{
        if(msg)msg.innerHTML='<span style="color:var(--red)">标签同步失败: '+esc(d.error||'?')+'</span>';
        setAliasRowMessage(row.email,'标签同步失败: '+(d.error||'?'),true);
    }
    }catch(e){
      if(msg)msg.innerHTML='<span style="color:var(--red)">'+esc(e.message||e)+'</span>';
      setAliasRowMessage(row.email,'标签同步失败: '+(e.message||e),true);
    }finally{
      if(btn){btn.disabled=false;btn.textContent='保存';}
    }
  };
  window.deleteAlias = function(idx){
    var row=emails[idx];
    if(!row)return;
    var h='<div class="modal-overlay" id="aliasActionModal" onclick="if(event.target===this)closeAliasModal()"><div class="modal-box alias-modal-danger"><h3><i class="diamond"></i> 删除隐私邮箱</h3><p>删除后这个地址通常不能恢复。项目会同时清理本地创建记录，避免下次刷新又显示出来。</p><div class="alias-modal-summary"><strong>'+esc(row.email||'')+'</strong><span>标签: '+esc(row.label||'-')+'</span><span>账号: '+esc(row.account_email||row.account_name||row.account_id||'-')+'</span></div><div class="modal-actions"><button class="btn btn-outline" onclick="closeAliasModal()">取消</button><button class="btn btn-danger" id="btnAliasDelete" onclick="confirmDeleteAlias('+idx+')">删除</button></div><div class="modal-msg" id="aliasModalMsg"></div></div></div>';
    document.body.insertAdjacentHTML('beforeend',h);
  };
  window.confirmDeleteAlias = async function(idx){
    var row=emails[idx];
    if(!row)return;
    var msg=E('aliasModalMsg');
    var btn=E('btnAliasDelete');
    if(btn){btn.disabled=true;btn.textContent='删除中...';}
    if(msg)msg.innerHTML='<span style="color:var(--ink-soft)">正在从 iCloud 删除...</span>';
    try{
      row=await resolveAliasForAction(row);
      var d=await apiSlow('/api/accounts/'+encodeURIComponent(row.account_id)+'/aliases/'+encodeURIComponent(row.anonymousId||'_')+'/delete',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:row.email||''})});
    if(d.ok){
        emails=emails.filter(function(e){return String(e.email||'').toLowerCase()!==String(row.email||'').toLowerCase();});
      clearAliasRowMessage(row.email);
      renderAliasTable();
      refreshAll();
        closeAliasModal();
      aliasToolbarStatus('已删除 '+(row.email||''),false);
    }else{
        if(msg)msg.innerHTML='<span style="color:var(--red)">删除失败: '+esc(d.error||'?')+'</span>';
        setAliasRowMessage(row.email,'删除失败: '+(d.error||'?'),true);
    }
    }catch(e){
      if(msg)msg.innerHTML='<span style="color:var(--red)">'+esc(e.message||e)+'</span>';
      setAliasRowMessage(row.email,'删除失败: '+(e.message||e),true);
    }finally{
      if(btn){btn.disabled=false;btn.textContent='删除';}
    }
  };
  window.renderAliasTable = function(){
    ensureAliasControls();
    renderAliasBatchSearchState();
    var c=E('aliasTableContainer');
    if(!c)return;
    var fullList=visibleAliasRows();
    pruneAliasSelection(fullList);
    E('emailCount').textContent=fullList.length+' / '+emails.length;
    updateAliasPager(fullList.length);
    if(!fullList.length){
      c.className='empty';
      c.innerHTML='<div class="empty"><div class="icon"></div>没有可显示的别名。点“云端同步”重新拉取 iCloud 当前账号里的 Hide My Email 别名。</div>';
      return;
    }
    c.className='';
    var list=pagedAliasRows(fullList);
    var selectedCount=selectedAliasRows().length;
    var h='<div class="alias-list"><div class="alias-list-head"><div class="alias-row-check"><input id="aliasSelectAll" type="checkbox" onchange="toggleAliasAll(this.checked)" title="全选当前页"></div><div class="alias-head-email"><span class="alias-head-title">邮箱</span>'+aliasHeadToolsHtml(selectedCount)+'</div><div>标签</div><div>iCloud账号</div><div>创建时间</div><div>状态</div></div>';
    list.forEach(function(e){
      var lifecycleDisabled=e.lifecycle_status==='disabled';
      var status=lifecycleDisabled?'已停用':(e.active===false?'停用':'活跃');
      var statusCls=lifecycleDisabled||e.active===false?'err':'ok';
      var account=aliasIcloudAccount(e);
      var label=e.label||'';
      var created=formatBeijingDateTime(e.created_at||e.createdAt||'');
      var idx=emails.indexOf(e);
      var source=e.source==='local'&&!e.anonymousId?'待同步':'';
      var pickupCount=parseInt(e.pickup_link_count||0)||0;
      var pickupEmails=Array.isArray(e.pickup_link_emails)?e.pickup_link_emails:[];
      var pickupState=pickupCount?'<div class="alias-pickup-state" title="'+escAttr(pickupEmails.join('\n'))+'">已生成取码链接'+(pickupCount>1?' '+pickupCount+' 个':'')+'</div>':'';
      var checked=_aliasSelection[aliasRowKey(e)]?' checked':'';
      var rowCls=checked?' selected':'';
      var deactivationTitle=lifecycleDisabled?'停用原因：ChatGPT 访问权限已停用\n识别别名：'+(e.deactivation_alias||e.email):source||status;
      h+='<div class="alias-row'+rowCls+'" data-email="'+escAttr(e.email)+'" onmousedown="startAliasRowDragSelect(event,&quot;'+escAttr(e.email)+'&quot;)" onmouseenter="enterAliasRowDragSelect(event,&quot;'+escAttr(e.email)+'&quot;)"><div class="alias-row-check" onmousedown="startAliasDragSelect(event,&quot;'+escAttr(e.email)+'&quot;)" onmouseenter="enterAliasDragSelect(event,&quot;'+escAttr(e.email)+'&quot;)"><input type="checkbox"'+checked+' onclick="event.preventDefault();event.stopPropagation()" title="按住这一行滑动可多选"></div><div class="alias-row-main"><div class="alias-cell-line"><span class="alias-email alias-cell-text" title="'+escAttr(e.email)+'">'+esc(e.email)+'</span><span class="alias-inline-actions"><button onmousedown="event.stopPropagation()" onclick="copyOne(\''+escAttr(e.email)+'\')" title="复制邮箱">复制</button><button class="danger" onmousedown="event.stopPropagation()" onclick="deleteAlias('+idx+')" title="从 iCloud 删除">删除</button></span></div>'+pickupState+'</div><div class="alias-row-meta"><div class="alias-cell-line"><span class="alias-inline-actions"><button onmousedown="event.stopPropagation()" onclick="editAliasLabel('+idx+')" title="同步修改 iCloud 标签">标签</button></span><span class="alias-label alias-cell-text" title="'+escAttr(label||'-')+'">'+esc(label||'-')+'</span></div></div><div class="alias-row-account"><div class="alias-cell-text" title="'+escAttr(account)+'">'+esc(account)+'</div></div><div class="alias-row-time"><div class="alias-cell-text" title="'+escAttr(created||source||'')+'">'+esc(created||source||'-')+'</div></div><div class="alias-row-state" title="'+escAttr(deactivationTitle)+'"><span class="alias-status-dot '+statusCls+'"></span><span class="alias-state-label">'+esc(status)+'</span></div>'+aliasRowMessageHtml(e.email)+'</div>';
    });
    h+='</div>';
    c.innerHTML=h;
    updateAliasSelectAllState();
  };
  window.copyOne = function(email){
    navigator.clipboard.writeText(email).then(function(){
      setAliasRowMessage(email,'已复制邮箱地址',false);
    }).catch(function(e){
      setAliasRowMessage(email,'复制失败: '+(e.message||e),true);
    });
  };
  window.copyAll = function(){
    var filter=E('aliasFilter')?E('aliasFilter').value:'all';
    var filtered=filter==='all'?emails:emails.filter(function(e){return e.account_id===filter});
    navigator.clipboard.writeText(filtered.map(function(e){return e.email}).join('\n')).then(function(){
      aliasToolbarStatus('已复制 '+filtered.length+' 个邮箱',false);
    }).catch(function(e){
      aliasToolbarStatus('复制失败: '+(e.message||e),true);
    });
  };
  window.copySelectedAliases = function(){
    var rows=selectedAliasRows();
    if(!rows.length){aliasToolbarStatus('请先选择邮箱',true);return;}
    navigator.clipboard.writeText(rows.map(function(e){return e.email}).join('\n')).then(function(){
      aliasToolbarStatus('已复制选中的 '+rows.length+' 个邮箱',false);
    }).catch(function(e){
      aliasToolbarStatus('复制失败: '+(e.message||e),true);
    });
  };
  window.bulkEditAliasLabels = function(){
    var rows=selectedAliasRows();
    if(!rows.length){aliasToolbarStatus('请先选择邮箱',true);return;}
    var sample=rows.slice(0,5).map(function(r){return '<span>'+esc(r.email)+'</span>';}).join('');
    var more=rows.length>5?'<span>另有 '+(rows.length-5)+' 个...</span>':'';
    var h='<div class="modal-overlay" id="aliasActionModal" onclick="if(event.target===this)closeAliasModal()"><div class="modal-box"><h3><i class="diamond"></i> 批量修改标签</h3><p>将为选中的 '+rows.length+' 个隐私邮箱同步修改 iCloud 标签。失败的邮箱会保留并在行内显示原因。</p><div class="alias-modal-summary"><strong>已选 '+rows.length+' 个</strong>'+sample+more+'</div><label style="font-family:var(--mono);font-size:11px;color:var(--ink-faint);letter-spacing:.2em;text-transform:uppercase">新标签</label><input type="text" id="bulkAliasLabelInput" value="" autocomplete="off"><div class="modal-actions"><button class="btn btn-outline" onclick="closeAliasModal()">取消</button><button class="btn btn-primary" id="btnBulkAliasLabel" onclick="confirmBulkAliasLabel()">保存</button></div><div class="modal-msg" id="aliasModalMsg"></div></div></div>';
    document.body.insertAdjacentHTML('beforeend',h);
    setTimeout(function(){var input=E('bulkAliasLabelInput');if(input)input.focus();},0);
  };
  window.confirmBulkAliasLabel = async function(){
    var rows=selectedAliasRows();
    var label=String((E('bulkAliasLabelInput')||{}).value||'').trim();
    var msg=E('aliasModalMsg');
    var btn=E('btnBulkAliasLabel');
    if(!rows.length){if(msg)msg.innerHTML='<span style="color:var(--red)">没有选中的邮箱</span>';return;}
    if(btn){btn.disabled=true;btn.textContent='同步中...';}
    var ok=0,fail=0;
    for(var i=0;i<rows.length;i++){
      var row=rows[i];
      if(msg)msg.innerHTML='<span style="color:var(--ink-soft)">正在同步 '+(i+1)+' / '+rows.length+'...</span>';
      try{
        row=await resolveAliasForAction(row);
        var d=await apiSlow('/api/accounts/'+encodeURIComponent(row.account_id)+'/aliases/'+encodeURIComponent(row.anonymousId||'_')+'/label',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({label:label,email:row.email||''})});
        if(d.ok){
          var latest=aliasByEmail(row.email);
          if(latest)latest.label=label;
          _aliasRowMessages[aliasMsgKey(row.email)]={text:'标签已同步',err:false};
          ok++;
        }else{
          _aliasRowMessages[aliasMsgKey(row.email)]={text:'标签同步失败: '+(d.error||'?'),err:true};
          fail++;
        }
      }catch(e){
        _aliasRowMessages[aliasMsgKey(row.email)]={text:'标签同步失败: '+(e.message||e),err:true};
        fail++;
      }
    }
    renderAliasTable();
    if(msg)msg.innerHTML='<span style="color:'+(fail?'#b36b00':'var(--green)')+'">完成：成功 '+ok+' 个，失败 '+fail+' 个</span>';
    aliasToolbarStatus('批量改标签完成：成功 '+ok+' 个，失败 '+fail+' 个',!!fail);
    if(btn){btn.disabled=false;btn.textContent='保存';}
  };
  window.bulkDeleteAliases = function(){
    var rows=selectedAliasRows();
    if(!rows.length){aliasToolbarStatus('请先选择邮箱',true);return;}
    var sample=rows.slice(0,6).map(function(r){return '<span>'+esc(r.email)+'</span>';}).join('');
    var more=rows.length>6?'<span>另有 '+(rows.length-6)+' 个...</span>':'';
    var h='<div class="modal-overlay" id="aliasActionModal" onclick="if(event.target===this)closeAliasModal()"><div class="modal-box alias-modal-danger"><h3><i class="diamond"></i> 批量删除隐私邮箱</h3><p>确认删除选中的 '+rows.length+' 个 Hide My Email 地址？删除会同步到 iCloud，通常不能恢复。</p><div class="alias-modal-summary"><strong>将删除 '+rows.length+' 个</strong>'+sample+more+'</div><div class="modal-actions"><button class="btn btn-outline" onclick="closeAliasModal()">取消</button><button class="btn btn-danger" id="btnBulkAliasDelete" onclick="confirmBulkDeleteAliases()">确认删除</button></div><div class="modal-msg" id="aliasModalMsg"></div></div></div>';
    document.body.insertAdjacentHTML('beforeend',h);
  };
  window.confirmBulkDeleteAliases = async function(){
    var rows=selectedAliasRows();
    var msg=E('aliasModalMsg');
    var btn=E('btnBulkAliasDelete');
    if(!rows.length){if(msg)msg.innerHTML='<span style="color:var(--red)">没有选中的邮箱</span>';return;}
    if(btn){btn.disabled=true;btn.textContent='删除中...';}
    var ok=0,fail=0,deleted={};
    for(var i=0;i<rows.length;i++){
      var row=rows[i];
      if(msg)msg.innerHTML='<span style="color:var(--ink-soft)">正在删除 '+(i+1)+' / '+rows.length+'...</span>';
      try{
        row=await resolveAliasForAction(row);
        var d=await apiSlow('/api/accounts/'+encodeURIComponent(row.account_id)+'/aliases/'+encodeURIComponent(row.anonymousId||'_')+'/delete',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:row.email||''})});
        if(d.ok){
          deleted[aliasRowKey(row)]=true;
          clearAliasRowMessage(row.email);
          ok++;
        }else{
          _aliasRowMessages[aliasMsgKey(row.email)]={text:'删除失败: '+(d.error||'?'),err:true};
          fail++;
        }
      }catch(e){
        _aliasRowMessages[aliasMsgKey(row.email)]={text:'删除失败: '+(e.message||e),err:true};
        fail++;
      }
    }
    emails=emails.filter(function(e){return !deleted[aliasRowKey(e)];});
    Object.keys(deleted).forEach(function(k){delete _aliasSelection[k];});
    renderAliasTable();
    refreshAll();
    if(msg)msg.innerHTML='<span style="color:'+(fail?'#b36b00':'var(--green)')+'">完成：删除 '+ok+' 个，失败 '+fail+' 个</span>';
    aliasToolbarStatus('批量删除完成：成功 '+ok+' 个，失败 '+fail+' 个',!!fail);
    if(btn){btn.disabled=false;btn.textContent='确认删除';}
  };
  var _inboxPrompted={};
  function inboxAccountById(accId){
    return accounts.find(function(a){return a.id===accId});
  }
  var _inboxStores={};
  var _inboxStore={accId:'',title:'',messages:[],selectedId:'',loaded:false};
  var _inboxRequestSeq=0;
  var _inboxActiveAccId='';
  var _inboxSearchActive=false;
  var INBOX_SELECTION_KEY='hme.inbox.selectedAccountId.v1';
  var _inboxSelectedAccountId=(function(){try{return localStorage.getItem(INBOX_SELECTION_KEY)||'';}catch(_){return '';}})();
  function rememberInboxAccount(accId){
    _inboxSelectedAccountId=String(accId||'');
    try{localStorage.setItem(INBOX_SELECTION_KEY,_inboxSelectedAccountId);}catch(_){}
  }
  var _inboxAutoTimer=null;
  var _inboxLoading={};
  var _inboxBusy=false;
  var _inboxSearchBusy=false;
  function inboxSearchQuery(){
    var input=E('aliasSearchInput');
    return input?String(input.value||'').trim():'';
  }
  function inboxSearchMode(){
    return _inboxSearchActive||_inboxSearchBusy||!!inboxSearchQuery();
  }
  function emptyInboxStore(accId){
    return {accId:accId||'',title:'',messages:[],selectedId:'',loaded:false,source:''};
  }
  function useInboxStore(accId){
    accId=accId||'';
    if(!_inboxStores[accId])_inboxStores[accId]=emptyInboxStore(accId);
    _inboxStore=_inboxStores[accId];
    return _inboxStore;
  }
  function currentInboxStore(){
    var sel=E('inboxAccount');
    return useInboxStore(sel?sel.value:'');
  }
  function mailSenderName(from){
    var s=String(from||'').replace(/"/g,'').trim();
    var m=s.match(/^(.*?)\s*<[^>]+>/);
    s=(m&&m[1]?m[1]:s).trim();
    return s||'未知发件人';
  }
  function mailInitial(from){
    var s=mailSenderName(from);
    return (s.charAt(0)||'?').toUpperCase();
  }
  function mailTime(date){
    return formatBeijingMailTime(date);
  }
  function mailTs(m){
    var d=parseAppDate((m&&m.date)||'');
    if(d)return d.getTime();
    var id=Number((m&&m.id)||0);
    return isNaN(id)?0:id;
  }
  function sortInboxMessages(msgs){
    return (msgs||[]).slice().sort(function(a,b){
      var av=mailTs(a),bv=mailTs(b);
      if(av!==bv)return bv-av;
      return String((b&&b.id)||'').localeCompare(String((a&&a.id)||''));
    });
  }
  function mailPreview(m){
    var body=String(m.body_preview||m.body||'').replace(/\s+/g,' ').trim();
    if(body)return body;
    return String(m.to?'To: '+m.to:'').replace(/\s+/g,' ').trim();
  }
  function inboxStatus(text){
    var el=E('cacheStatus');
    if(el)el.textContent=text?' | '+text:'';
  }
  function updateCacheStatus(cached){
    var el=E('cacheStatus');
    if(!el)return;
    if(!cached){
      el.textContent='';
      return;
    }
    var count=Number(cached.inbox_cached||cached.alias_cached||0);
    var age=cached.cache_age_sec;
    var ageText='';
    if(typeof age==='number'&&isFinite(age)&&age>=0){
      ageText=age<60?Math.round(age)+'s':Math.round(age/60)+'m';
    }
    el.textContent=count?' | '+count+' 封已缓存'+(ageText?' '+ageText+' 前':''):'';
  }
  function rxEsc(s){
    return String(s).replace(/[.*+?^${}()|[\]\\]/g,'\\$&');
  }
  function cleanLinkLabelText(label){
    return String(label||'')
      .replace(/[\[\]{}]/g,' ')
      .replace(/\s+/g,' ')
      .replace(/^[<>\s"'“”‘’().,，。:：;；-]+/g,'')
      .replace(/[<>\s"'“”‘’().,，。:：;；-]+$/g,'')
      .trim();
  }
  function linkLabelKey(label){
    return cleanLinkLabelText(label).toLowerCase().replace(/\s+/g,' ');
  }
  function localizedLinkLabel(url,label){
    var clean=cleanLinkLabelText(label);
    var lower=clean.toLowerCase();
    var host='';
    try{host=new URL(url).hostname.replace(/^www\./,'').toLowerCase();}catch(_){}
    if(/help center|help centre|帮助中心|幫助中心/.test(lower)||host==='help.openai.com')return '帮助中心';
    if(/contact|联系我们|與我們聯繫|与我们联系/.test(lower))return '联系我们';
    if(/manage.*account|account settings|管理.*账户|管理.*帐户|管理.*賬戶/.test(lower))return '管理账户';
    if(/manage.*subscription|subscription settings|cancel.*subscription|管理订阅|取消订阅/.test(lower))return '管理订阅';
    if(/成功订阅|new subscription|your subscription|subscribed/.test(lower))return '查看订阅';
    if(/appeal|申诉|申訴/.test(lower))return '提交申诉';
    if(/verify|verification|验证|驗證/.test(lower))return '打开验证链接';
    if(host==='chatgpt.com'||host==='chat.openai.com'||host.endsWith('.chatgpt.com')){
      if(/subscription|plus|订阅|套餐/.test(lower))return '查看订阅';
      return '打开 ChatGPT';
    }
    if(host.indexOf('openai.com')>=0){
      if(/help|support/.test(lower))return '帮助中心';
      if(/subscription|plus|订阅|套餐/.test(lower))return '查看订阅';
      return '打开 OpenAI';
    }
    if(host.indexOf('sendgrid.net')>=0||/^u\d+\./.test(host)){
      if(/chatgpt|chatgpt\.com/.test(lower))return '打开 ChatGPT';
      if(/openai/.test(lower))return '打开 OpenAI';
      if(/help/.test(lower))return '帮助中心';
      if(/contact/.test(lower))return '联系我们';
      if(/manage|subscription|订阅/.test(lower))return '管理订阅';
      return '打开链接';
    }
    if(!clean||/^[a-z0-9.-]+\.[a-z]{2,}$/i.test(clean)||(!/[\u4e00-\u9fff]/.test(clean)&&clean.length>32))return '打开链接';
    return clean;
  }
  function cleanMailText(raw){
    var text=String(raw||'').replace(/\r\n/g,'\n').replace(/\r/g,'\n');
    var hidden=0, links=[], seenLinks={};
    var urlRe=/https?:\/\/[^\s<>"')]+/g;
    var lines=text.split('\n'), kept=[];
    lines.forEach(function(line){
      line=String(line||'').replace(/\u00a0/g,' ').trim();
      if(!line)return;
      var linkOnlyKeys=[];
      var urls=line.match(urlRe)||[];
      var hadUrls=!!urls.length;
      urls.forEach(function(url){
        var cleanUrl=String(url||'').replace(/[),.;]+$/,'');
        var label=line.replace(url,' ').replace(/[()<>[\]]/g,' ').replace(/[ \t]{2,}/g,' ').trim();
        if(!label||label.length>44){
          try{label=new URL(cleanUrl).hostname.replace(/^www\./,'');}catch(_){label='打开链接'}
        }
        if(!seenLinks[cleanUrl]){
          links.push({url:cleanUrl,label:localizedLinkLabel(cleanUrl,label)});
          seenLinks[cleanUrl]=1;
        }
        linkOnlyKeys.push(linkLabelKey(label));
        hidden++;
        line=line.replace(new RegExp('\\s*\\(?'+rxEsc(url)+'\\)?','g'),' ');
      });
      line=line
        .replace(/<\s*>/g,' ')
        .replace(/\(\s*\)/g,' ')
        .replace(/\[\s*\]/g,' ')
        .replace(/\s+([,.，。；;:：])/g,'$1')
        .replace(/^[<>.\s。．,，、;；:：-]+/g,'')
        .replace(/[ \t]{2,}/g,' ')
        .trim();
      if(!line)return;
      if(/^[<>.\s。．,，、;；:：-]+$/.test(line))return;
      if(hadUrls&&linkOnlyKeys.indexOf(linkLabelKey(line))>=0)return;
      if(/^[-_=]{3,}$/.test(line))return;
      if(/^(view in browser|unsubscribe|manage preferences)$/i.test(line))return;
      kept.push(line);
    });
    return {text:kept.join('\n').replace(/\n{3,}/g,'\n\n').trim(),hidden:hidden,links:links};
  }
  function mailVerificationCode(raw,subject){
    var text=String(subject||'')+'\n'+String(raw||'');
    var preferred=/(?:验证码|验证代码|登录代码|临时代码|code)[^\d]{0,28}(\d{4,8})/ig;
    var m=preferred.exec(text);
    if(m&&m[1])return m[1];
    var any=/(?:^|\D)(\d{6})(?!\d)/g;
    m=any.exec(text);
    return m&&m[1]?m[1]:'';
  }
  window.copyMailCode=function(code){
    navigator.clipboard.writeText(String(code||'')).then(function(){toast('验证码已复制')});
  };
  function formatMailBodyHtml(msg){
    var raw=String((msg&&msg.body)||(msg&&msg.body_preview)||'').trim();
    if(!raw)return '暂无正文内容';
    var cleaned=cleanMailText(raw);
    var code=mailVerificationCode(raw,msg?msg.subject:'');
    var parts=[];
    if(code){
      parts.push('<div class="mail-code-card"><div class="mail-code-label">验证码</div><button class="mail-code-value" onclick="copyMailCode(&quot;'+escAttr(code)+'&quot;)" title="复制验证码">'+esc(code)+'</button></div>');
    }
    var paragraphs=[];
    (cleaned.text?cleaned.text.split('\n'):[]).forEach(function(line){
      line=line.trim();
      if(!line)return;
      if(code){
        line=line.replace(new RegExp('(^|\\D)'+rxEsc(code)+'(?!\\d)'),'$1').replace(/[：:]\s*$/,'：').trim();
      }
      if(!line)return;
      if(/^(OpenAI|ChatGPT)$/i.test(line)&&paragraphs.length===0)return;
      paragraphs.push('<p>'+esc(line)+'</p>');
    });
    if(paragraphs.length)parts.push('<div class="mail-clean-body">'+paragraphs.join('')+'</div>');
    var actionLinks=(cleaned.links||[]).filter(function(link){
      return /^https?:\/\//.test(link.url||'');
    });
    if(actionLinks.length){
      var linkHtml=actionLinks.slice(0,4).map(function(link){
        return '<a href="'+escAttr(link.url)+'" target="_blank" rel="noopener noreferrer" title="'+escAttr(link.url)+'">'+esc(link.label||'打开链接')+'</a>';
      }).join('');
      parts.push('<div class="mail-link-actions">'+linkHtml+'</div>');
    }
    if(cleaned.hidden>actionLinks.slice(0,4).length){
      parts.push('<div class="mail-hidden-links">另有 '+(cleaned.hidden-actionLinks.slice(0,4).length)+' 条长链接已折叠</div>');
    }
    return parts.join('')||'暂无正文内容';
  }
  function renderInboxReader(msg,loading){
    var pane=E('icloudReader');
    if(!pane)return;
    if(!msg){
      pane.innerHTML='<div class="icloud-reader-empty">选择一封邮件</div>';
      return;
    }
    var from=mailSenderName(msg.from);
    var body='';
    if(loading){
      body='<div class="mail-loading-skeleton" aria-label="正在载入正文"><span></span><span></span><span></span></div>';
    }else{
      body=formatMailBodyHtml(msg);
    }
    var account=inboxAccountById(msg.account_id||'');
    var accountText=account?compactAccountSelectLabel(account):(msg.account_icloud_email||'');
    pane.innerHTML='<div class="icloud-reader-head"><div class="icloud-reader-subject">'+esc(msg.subject||'(无主题)')+'</div><div class="icloud-reader-meta"><div class="icloud-mail-avatar">'+esc(mailInitial(msg.from))+'</div><div class="icloud-reader-meta-main"><b>'+esc(from)+'</b><br>收件人: '+esc(msg.to||'-')+(accountText?'<br>账号: '+esc(accountText):'')+'</div><div class="icloud-reader-date">'+esc(mailTime(msg.date))+'</div></div></div><div class="icloud-reader-body">'+body+'</div>';
  }
  window.selectInboxMessage = async function(messageKey,loadBody){
    var store=currentInboxStore();
    var msg=(store.messages||[]).find(function(m,i){return inboxMessageKey(m,i)===String(messageKey)});
    if(!msg)return;
    store.selectedId=String(messageKey);
    document.querySelectorAll('.icloud-mail-row').forEach(function(row){
      row.classList.toggle('active',row.getAttribute('data-msgkey')===String(messageKey));
    });
    renderInboxReader(msg,loadBody!==false&&!msg.body&&!!msg.id);
    if(loadBody===false||msg.body||!msg.id||msg._bodyLoading)return;
    var accId=msg.account_id||E('inboxAccount').value;
    if(!accId||accId==='all')return;
    msg._bodyLoading=true;
    try{
      var d=await apiSlow('/api/accounts/'+encodeURIComponent(accId)+'/message/'+encodeURIComponent(msg.id));
      if(currentInboxStore()!==store)return;
      if(d.ok&&d.message){
        msg.body=d.message.body||msg.body||'';
        msg.content_type=d.message.content_type||'';
      }else{
        msg.body='正文获取失败: '+(d.error||'未知错误');
      }
    }finally{
      msg._bodyLoading=false;
    }
    if(currentInboxStore()===store&&store.selectedId===String(messageKey))renderInboxReader(msg,false);
  };
  window.createPickupLinksForSelected=function(){
    var rows=selectedAliasRows();
    if(!rows.length){aliasToolbarStatus('请先选择邮箱',true);return;}
    if(typeof openPickupBatchModal!=='function'||typeof generatePickupLinksBatch!=='function'){
      aliasToolbarStatus('取码链接功能尚未加载',true);
      return;
    }
    openPickupBatchModal(rows.map(function(row){return row.email;}).join('\n'));
    var statusEl=E('pickupBatchStatus');
    if(statusEl)statusEl.textContent='已载入 '+rows.length+' 个邮箱；原邮箱始终生成，数量表示额外 8 位随机别名个数。';
  };
  function mergeInboxBody(messageKey,full,store){
    store=store||currentInboxStore();
    var msg=(store.messages||[]).find(function(m,i){return inboxMessageKey(m,i)===String(messageKey)});
    if(msg&&full){
      msg.body=full.body||msg.body||'';
      msg.content_type=full.content_type||msg.content_type||'';
      return msg;
    }
    return null;
  }
  function prefetchInboxBodies(accId,msgs,selectedId,store){
    if(!accId||!msgs||!msgs.length)return;
    store=store||useInboxStore(accId);
    var selected=msgs.find(function(m,i){return inboxMessageKey(m,i)===String(selectedId)});
    if(!selected||!selected.id||selected.body)return;
    var owner=selected.account_id||accId;
    if(!owner||owner==='all')return;
    api('/api/accounts/'+encodeURIComponent(owner)+'/messages/prefetch',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ids:[String(selected.id)]}),timeout:60000}).then(function(d){
      if(currentInboxStore()!==store||!d.ok||!d.messages)return;
      Object.keys(d.messages).forEach(function(id){
        mergeInboxBody(owner+'::'+id,d.messages[id],store);
      });
    });
  }
  function inboxMessageKey(message,index){
    var accountId=String((message&&message.account_id)||'');
    var messageId=String((message&&message.id)||('m'+(index||0)));
    return accountId+'::'+messageId;
  }
  function inboxRowContent(message){
    var account=inboxAccountById(message.account_id||'');
    var accountLabel=account?compactAccountSelectLabel(account):(message.account_icloud_email||'');
    var accountHtml=E('inboxAccount')&&E('inboxAccount').value==='all'?'<div class="icloud-mail-account">'+esc(accountLabel)+'</div>':'';
    return '<div class="icloud-mail-avatar">'+esc(mailInitial(message.from))+'</div><div class="icloud-mail-main"><div class="icloud-mail-sender">'+esc(mailSenderName(message.from))+'</div><div class="icloud-mail-subject">'+esc(message.subject||'(无主题)')+'</div><div class="icloud-mail-preview">'+esc(mailPreview(message))+'</div>'+accountHtml+'</div><div class="icloud-mail-time">'+esc(mailTime(message.date))+'</div>';
  }
  function patchInboxList(messages,title,selected){
    var container=E('inboxMsgs');
    if(!container)return;
    container.className='';
    var shell=container.querySelector('.icloud-mail-shell');
    if(!shell){
      container.innerHTML='<div class="icloud-mail-shell"><div class="icloud-mail-list-pane"><div class="icloud-mail-list-head"><div class="icloud-mail-title">收件箱</div><div class="icloud-mail-count"></div></div><div class="icloud-mail-list"></div></div><div class="icloud-mail-reader-pane" id="icloudReader"></div></div>';
      shell=container.querySelector('.icloud-mail-shell');
    }
    shell.querySelector('.icloud-mail-count').textContent=title||('收件箱 ('+messages.length+' 封)');
    var list=shell.querySelector('.icloud-mail-list');
    var existing={};
    list.querySelectorAll('.icloud-mail-row').forEach(function(row){existing[row.dataset.msgkey]=row;});
    messages.forEach(function(message,index){
      var key=inboxMessageKey(message,index);
      var row=existing[key];
      if(!row){
        row=document.createElement('div');
        row.className='icloud-mail-row';
        row.dataset.msgkey=key;
        row.addEventListener('click',function(){window.selectInboxMessage(row.dataset.msgkey,true);});
      }
      var content=inboxRowContent(message);
      if(row.dataset.rendered!==content){row.innerHTML=content;row.dataset.rendered=content;}
      row.classList.toggle('active',key===selected);
      list.appendChild(row);
      delete existing[key];
    });
    Object.keys(existing).forEach(function(key){existing[key].remove();});
  }
  window.renderInboxMsgs = function(msgs,title,accId){
    msgs=sortInboxMessages(msgs||[]);
    var selectedAccId=E('inboxAccount')?E('inboxAccount').value:'';
    accId=accId||selectedAccId;
    var store=useInboxStore(accId);
    store.accId=accId;
    store.messages=msgs;
    store.title=title||'收件箱';
    store.loaded=true;
    if(selectedAccId&&selectedAccId!==accId)return;
    var c=E('inboxMsgs');
    if(!c)return;
    c.className='';
    if(!msgs.length){
      c.innerHTML='<div class="empty"><div class="icon"></div>收件箱为空</div>';
      return;
    }
    var selected=store.selectedId;
    if(!msgs.some(function(m,i){return inboxMessageKey(m,i)===String(selected)})){
      selected=inboxMessageKey(msgs[0],0);
      store.selectedId=selected;
    }
    patchInboxList(msgs,title,selected);
    selectInboxMessage(selected,true);
    prefetchInboxBodies(accId,msgs,selected,store);
  };
  function renderInboxSetup(accId){
    var acc=inboxAccountById(accId);
    if(!acc){E('inboxMsgs').innerHTML='<div class="empty"><div class="icon"></div>请先选择账号</div>';return;}
    var email=acc.icloud_email||acc.real_email||'';
    E('inboxMsgs').innerHTML='<div class="empty"><div class="icon"></div><div style="font-weight:700;margin-bottom:8px">需要设置 App 专用密码后才能收件</div><div style="max-width:560px;margin:0 auto 16px;line-height:1.7;color:var(--ink-soft)">项目登录已经读取到 iCloud 别名，但 IMAP 收件必须使用 Apple 单独生成的 App 专用密码。邮箱地址已自动识别为 <code>'+esc(email||'未识别')+'</code>，不对时再改。</div><button class="btn btn-primary" onclick="showAppPwdModal(\''+escAttr(accId)+'\')">联动设置收件箱</button></div>';
  }
  function reorderInboxToolbar(){
    ensureInboxControls();
    var bar=document.querySelector('#view-inbox .panel-header>div');
    if(!bar)return;
    var buttons=Array.prototype.slice.call(bar.querySelectorAll('button'));
    var search=buttons.find(function(b){return b.textContent.trim()==='查件';});
    var refresh=buttons.find(function(b){return b.textContent.trim()==='刷新';});
    if(search&&refresh&&search.nextElementSibling!==refresh){
      bar.insertBefore(search,refresh);
    }
  }
  function ensureInboxControls(){
    var limit=E('inboxLimit');
    var limitHtml='<option value="10">10</option><option value="20">20</option><option value="50">50</option><option value="100">100</option><option value="200">200</option>';
    if(limit&&limit.tagName!=='SELECT'){
      var selected=String(limit.value||'20');
      var sel=document.createElement('select');
      sel.id='inboxLimit';
      sel.title='查件和全部扫描数量';
      sel.innerHTML=limitHtml;
      sel.value=['10','20','50','100','200'].indexOf(selected)>=0?selected:'20';
      limit.replaceWith(sel);
    }else if(limit){
      var current=String(limit.value||'20');
      limit.title='查件和全部扫描数量';
      limit.innerHTML=limitHtml;
      limit.value=['10','20','50','100','200'].indexOf(current)>=0?current:'20';
    }
    var scan=E('aliasScanLimit');
    if(scan)scan.remove();
  }
  function compactAccountSelectLabel(a){
    var email=String(a.icloud_email||a.real_email||'').trim();
    var name=String(accountDisplayName(a)||'').trim();
    if(!name)name=email||String(a.id||'');
    if(email&&name.toLowerCase()===email.toLowerCase())return email;
    if(email&&name.toLowerCase().indexOf(email.toLowerCase())>=0)return name;
    return email?name+' | '+email:name;
  }
  function syncInboxSelectWidget(sel){
    return sel;
  }
  window.updateInboxAccountSelect = function(opts){
    opts=opts||{};
    ensureInboxControls();
    var sel=E('inboxAccount');
    if(!sel)return;
    if(!accounts.length&&_refreshBusy&&!opts.accountsLoaded){
      sel.innerHTML='<option value="">正在读取账号...</option>';
      sel.disabled=true;
      var pendingSettings=E('btnInboxSettings');
      if(pendingSettings)pendingSettings.hidden=true;
      if(curTab==='inbox'&&!opts.passive)E('inboxMsgs').innerHTML='<div class="icloud-reader-empty">正在读取账号...</div>';
      return;
    }
    sel.disabled=false;
    var old=opts.prefer||_inboxSelectedAccountId||sel.value;
    var usable=accounts.filter(function(a){return a.status==='active'});
    var list=usable.length?usable:accounts;
    sel.innerHTML=list.length?'<option value="all">全部账号</option>':'<option value="">-- 暂无账号 --</option>';
    list.forEach(function(a){
      var hasPwd=a.has_app_password?' [收件可用]':' [待设置]';
      var label=compactAccountSelectLabel(a);
      sel.innerHTML+='<option value="'+escAttr(a.id)+'">'+esc(label.substring(0,72))+hasPwd+'</option>';
    });
    var next=old==='all'?'all':((old&&list.some(function(a){return a.id===old}))?old:(list.length?'all':''));
    sel.value=next;
    rememberInboxAccount(next);
    syncInboxSelectWidget(sel);
    var settings=E('btnInboxSettings');
    if(settings)settings.hidden=!next||next==='all';
    if(opts.passive)return;
    var store=useInboxStore(next);
    if(curTab==='inbox'){
      if(!next){E('inboxMsgs').innerHTML='<div class="empty"><div class="icon"></div>请先添加账号</div>';return;}
      var acc=next==='all'?null:inboxAccountById(next);
      if(acc&&!acc.has_app_password){
        renderInboxSetup(next);
        return;
      }
      if(store.loaded){
        if(store.messages&&store.messages.length)renderInboxMsgs(store.messages,store.title,next);
        else E('inboxMsgs').innerHTML='<div class="empty"><div class="icon"></div>这个账号的收件箱为空</div>';
      }else{
        E('inboxMsgs').className='';
        E('inboxMsgs').innerHTML='<div class="icloud-reader-empty">正在打开收件箱...</div>';
      }
      if(opts.skipLoad)return;
      setTimeout(function(){
        var current=E('inboxAccount');
        if(curTab==='inbox'&&current&&current.value===next&&typeof window.refreshInbox==='function'){
          window.refreshInbox({cacheOnly:true}).then(function(){
            if(curTab==='inbox'&&E('inboxAccount').value===next&&!inboxSearchMode())window.refreshInbox({refresh:true,background:true});
          });
        }
      },0);
    }
  };
  window.handleInboxAccountChange=function(){
    var sel=E('inboxAccount');
    _inboxSearchActive=false;
    var searchInput=E('aliasSearchInput');
    if(searchInput)searchInput.value='';
    rememberInboxAccount(sel?sel.value:'');
    var settings=E('btnInboxSettings');
    if(settings)settings.hidden=!sel||!sel.value||sel.value==='all';
    updateInboxAccountSelect({prefer:sel?sel.value:'',skipLoad:false});
  };
  window.handleInboxLimitChange=function(){
    if(inboxSearchQuery()){window.searchAliasMail();return;}
    window.refreshInbox({cacheOnly:true}).then(function(){window.refreshInbox({refresh:true,background:true});});
  };
  window.refreshCurrentInboxView=function(){
    if(inboxSearchQuery()){window.searchAliasMail();return;}
    window.refreshInbox({refresh:true});
  };
  window.openInboxSettings = function(){
    var accId=E('inboxAccount').value;
    if(!accId||accId==='all'){toast('请先选择一个具体账号',true);return}
    showAppPwdModal(accId);
  };
  window.refreshInbox = async function(options){
    if(typeof options==='boolean')options={refresh:options};
    options=options||{refresh:true};
    if(inboxSearchMode()&&!options.allowDuringSearch)return Promise.resolve();
    if(!options.background)_inboxSearchActive=false;
    var accountEl=E('inboxAccount');
    var accId=accountEl?accountEl.value:'';
    if(!accId){E('inboxMsgs').innerHTML='<div class="empty"><div class="icon"></div>请先选择账号</div>';return}
    var requestKey=accId+':'+(options.cacheOnly?'cache':'refresh');
    if(_inboxLoading[requestKey])return _inboxLoading[requestKey];
    var requestSeq=++_inboxRequestSeq;
    _inboxActiveAccId=accId;
    _inboxBusy=true;
    var store=useInboxStore(accId);
    var acc=accId==='all'?null:inboxAccountById(accId);
    if(acc&&!acc.has_app_password){
      _inboxBusy=false;
      _inboxActiveAccId='';
      renderInboxSetup(accId);
      return;
    }
    function finishBusy(){
      if(requestSeq===_inboxRequestSeq){
        _inboxBusy=false;
        _inboxActiveAccId='';
      }
    }
    function stillCurrent(){
      return requestSeq===_inboxRequestSeq&&E('inboxAccount')&&E('inboxAccount').value===accId&&!inboxSearchMode();
    }
    var watchdog=setTimeout(function(){
      if(stillCurrent()&&!store.loaded){
        renderInboxError(accId,'收件箱接口超时，数据没有返回。');
        finishBusy();
      }
    },options.cacheOnly?12000:60000);
    var task=(async function(){try{
      var limit=parseInt(E('inboxLimit').value)||20;
      if(store.loaded&&store.messages.length){
        renderInboxMsgs(store.messages,store.title,accId);
        if(!options.cacheOnly&&!options.background)inboxStatus('正在刷新...');
      }else{
        E('inboxMsgs').className='';
        E('inboxMsgs').innerHTML='<div class="icloud-reader-empty">正在打开收件箱...</div>';
      }
      var url=accId==='all'?'/api/inbox?limit='+limit:'/api/accounts/'+encodeURIComponent(accId)+'/inbox?limit='+limit;
      if(options.cacheOnly)url+='&cache_only=1';
      else if(accId==='all')url+='&refresh=1';
      else url+='&force=1';
      var d=await apiSlow(url);
      if(!stillCurrent())return;
      if(d.error&&!d.emails){renderInboxError(accId,d.error);return;}
      try{
        renderInboxMsgs(d.emails||[],(accId==='all'?'全部账号':'收件箱')+' ('+(d.count||0)+' 封)',accId);
      }catch(renderErr){
        renderInboxError(accId,'收件箱渲染失败: '+(renderErr&&renderErr.message?renderErr.message:renderErr));
        return;
      }
      updateCacheStatus(d.cached);
      if(!options.cacheOnly){
        var failed=(d.errors||[]).length;
        inboxStatus(failed?('已刷新，'+failed+' 个账号失败'):'刚刚已刷新');
      }
    }catch(e){
      if(stillCurrent())renderInboxError(accId,e&&e.message?e.message:e||'连接失败');
    }finally{
      clearTimeout(watchdog);
      finishBusy();
      delete _inboxLoading[requestKey];
    }
    })();
    _inboxLoading[requestKey]=task;
    return task;
  };
  window.setAppPassword = async function(accId){
    var pwd=E('appPwdInput').value.trim();
    var email=E('icloudEmailInput').value.trim();
    if(!email){E('appPwdMsg').innerHTML='<span style="color:var(--red)">请输入 iCloud 邮箱</span>';return}
    if(!/(@icloud\.com|@icloud\.com\.cn|@me\.com|@mac\.com)$/i.test(email)){
      E('appPwdMsg').innerHTML='<span style="color:var(--red)">这里不能填 Apple ID: '+esc(email)+'。请填写真正的 iCloud 邮箱，例如 xxx@icloud.com。</span>';
      return;
    }
    if(!pwd){E('appPwdMsg').innerHTML='<span style="color:var(--red)">请输入 App 专用密码</span>';return}
    var btn=E('btnSetPwd');btn.disabled=true;btn.textContent='测试中...';
    var d=await api('/api/accounts/'+encodeURIComponent(accId)+'/app-password',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({app_password:pwd,icloud_email:email}),timeout:60000});
    btn.disabled=false;btn.textContent='保存、测试并刷新收件箱';
    if(d.ok){
      E('appPwdMsg').innerHTML='<span style="color:var(--green)">连接成功! 收件箱 '+(d.inbox_count||0)+' 封，正在刷新...</span>';
      var acc=inboxAccountById(accId);
      if(acc){acc.has_app_password=true;acc.icloud_email=email;acc.app_password=pwd;}
      updateInboxAccountSelect();
      setTimeout(function(){closeAppPwdModal();refreshInbox(true);},900);
    }else if(d.saved){
      E('appPwdMsg').innerHTML='<span style="color:#b36b00">已保存，但测试失败: '+esc(d.error||'连接测试失败')+'</span>';
      var acc=inboxAccountById(accId);
      if(acc){acc.has_app_password=true;acc.icloud_email=email;acc.app_password=pwd;acc.last_mail_error=d.error||'';}
      updateInboxAccountSelect();
    }else{
      E('appPwdMsg').innerHTML='<span style="color:var(--red)">'+esc(d.error||'连接失败，请确认复制的是 App 专用密码，不是 Apple ID 登录密码')+'</span>';
    }
  };
  function accountDisplayName(a){
    if(!a)return '';
    var generic=!a.name||a.name==='iCloud 登录账号'||a.name==='未命名账号';
    return generic?(a.icloud_email||a.real_email||a.id):a.name;
  }
  function accountSubParts(a){
    var parts=[];
    if(!a)return parts;
    if(a.real_email)parts.push(['Apple ID',a.real_email]);
    if(a.icloud_email&&a.icloud_email!==a.real_email)parts.push(['iCloud',a.icloud_email]);
    return parts;
  }
  function accountSubline(a){
    return accountSubParts(a).map(function(p){return p[0]+': '+p[1]}).join(' · ');
  }
  function accountSubHtml(a){
    var parts=accountSubParts(a);
    if(!parts.length)return '';
    return parts.map(function(p){
      return '<span class="account-meta-line">'+esc(p[0]+': '+p[1])+'</span>';
    }).join('');
  }
  function accountHealth(a){
    if(!a||a.status==='error')return {cls:'error',badge:'err',title:'异常'};
    if(a.status==='warning')return {cls:'warn',badge:'warn',title:'待确认'};
    if(a.last_mail_error||a.last_error)return {cls:'warn',badge:'warn',title:'有警告'};
    return {cls:'active',badge:'ok',title:'正常'};
  }
  window.renderSidebar = function(){
    var c=E('sidebarAccounts');
    if(!c)return;
    if(!accounts.length){
      c.innerHTML='<div style="padding:8px 14px;font-size:11px;color:var(--ink-faint)">暂无账号</div>';
      return;
    }
    var trashIcon='<svg viewBox="0 0 24 24" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 6h18"></path><path d="M8 6V4h8v2"></path><path d="M19 6l-1 14H6L5 6"></path><path d="M10 11v5"></path><path d="M14 11v5"></path></svg>';
    c.innerHTML=accounts.map(function(a){
      var health=accountHealth(a);
      var title=esc(accountDisplayName(a));
      return '<div class="account-item" data-accid="'+escAttr(a.id)+'" onclick="goAccountInbox(&quot;'+escAttr(a.id)+'&quot;)" title="'+escAttr(accountSubline(a))+'"><span class="acc-dot '+health.cls+'" title="'+health.title+'"></span><span class="acc-name">'+title+'</span><button class="acc-del account-trash" type="button" title="退出账号" aria-label="退出账号" onclick="event.stopPropagation();removeAccount(&quot;'+escAttr(a.id)+'&quot;)">'+trashIcon+'</button></div>';
    }).join('');
  };
  window.closeAccountRemoveModal=function(){var m=E('accountRemoveModal');if(m)m.remove()};
  window.removeAccount=function(accId){
    var a=accounts.find(function(x){return x.id===accId});
    if(!a){toast('账号不存在',true);return}
    var h='<div class="modal-overlay" id="accountRemoveModal" onclick="if(event.target===this)closeAccountRemoveModal()"><div class="modal-box alias-modal-danger"><h3><i class="diamond"></i> 退出账号</h3><p>只退出这个 iCloud 登录账号。退出后后台邮箱列表和收码台会隐藏该账号数据；本地历史文件不会删除，重新登录账号后再同步显示。</p><div class="alias-modal-summary"><strong>'+esc(accountDisplayName(a))+'</strong><span>Apple ID: '+esc(a.real_email||'-')+'</span><span>iCloud: '+esc(a.icloud_email||'-')+'</span></div><div class="modal-actions"><button class="btn btn-outline" onclick="closeAccountRemoveModal()">取消</button><button class="btn btn-danger" id="btnRemoveAccount" onclick="confirmRemoveAccount(&quot;'+escAttr(accId)+'&quot;)">退出</button></div><div class="modal-msg" id="accountRemoveMsg"></div></div></div>';
    document.body.insertAdjacentHTML('beforeend',h);
  };
  window.confirmRemoveAccount=async function(accId){
    var btn=E('btnRemoveAccount'),msg=E('accountRemoveMsg');
    if(btn){btn.disabled=true;btn.textContent='退出中...';}
    if(msg)msg.innerHTML='<span style="color:var(--ink-soft)">正在退出账号登录，后台数据会隐藏...</span>';
    var d=await api('/api/accounts/'+encodeURIComponent(accId)+'/remove',{method:'POST'});
    if(d.ok){
      closeAccountRemoveModal();
      toast(d.message||'账号已退出，后台数据已隐藏');
      await refreshAll();
    }else{
      if(msg)msg.innerHTML='<span style="color:var(--red)">'+esc(d.error||'退出失败')+'</span>';
      if(btn){btn.disabled=false;btn.textContent='退出';}
    }
  };
  var _accountCardMessages={};
  function accountCardMessage(accId){
    var item=_accountCardMessages[accId];
    if(!item)return '<div class="account-card-msg"></div>';
    return '<div class="account-card-msg '+(item.err?'err':(item.warn?'warn':''))+'">'+esc(item.text||'')+'</div>';
  }
  function setAccountCardMessage(accId,text,isErr,isWarn){
    _accountCardMessages[accId]={text:text,err:!!isErr,warn:!!isWarn};
    renderDashboard();
  }
  window.renderDashboard = function(){
    var cards=E('summaryCards'),accCards=E('accCards');
    if(cards){
      var warnCount=state.warning_accounts||0;
      cards.innerHTML='<div class="card"><div class="label">账号总数</div><div class="value blue">'+(state.account_count||accounts.length||0)+'</div><div class="sub">活跃 '+(state.active_accounts||0)+' / 待确认 '+warnCount+' / 异常 '+(state.error_accounts||0)+'</div></div><div class="card"><div class="label">别名总数</div><div class="value green">'+(state.total_aliases||state.alias_count||0)+'</div><div class="sub">活跃 '+(state.total_active_aliases||state.alias_active||0)+'</div></div><div class="card"><div class="label">今日创建</div><div class="value accent">'+(state.today_created||0)+'</div><div class="sub">累计 '+(state.total_created||0)+'</div></div>';
    }
    if(!accCards)return;
    if(!accounts.length){
      accCards.innerHTML='<div class="empty"><div class="icon"></div>暂无账号，点击添加账号开始</div>';
      return;
    }
    accCards.innerHTML=accounts.map(function(a){
      var health=accountHealth(a);
      var title=accountDisplayName(a);
      var sub=accountSubHtml(a);
      return '<div class="acc-card" data-accid="'+escAttr(a.id)+'"><div class="acc-header"><span class="account-status-dot '+health.cls+'" title="'+health.title+'"></span><div class="acc-main" title="'+escAttr(health.title)+'"><div class="acc-title">'+esc(title)+'</div><div class="acc-email">'+sub+'</div></div></div><div class="acc-stats"><div class="acc-stat">别名: <span class="n">'+(a.alias_total||0)+'</span></div><div class="acc-stat">活跃: <span class="n" style="color:var(--green)">'+(a.alias_active||0)+'</span></div></div><div class="acc-actions"><button class="btn btn-outline btn-sm" onclick="createForAccount(&quot;'+escAttr(a.id)+'&quot;,1)">创建 1 个</button><button class="btn btn-outline btn-sm" onclick="createForAccount(&quot;'+escAttr(a.id)+'&quot;,5)">创建 5 个</button><button class="btn btn-outline btn-sm" onclick="validateAccount(&quot;'+escAttr(a.id)+'&quot;)">校验</button></div>'+accountCardMessage(a.id)+'</div>';
    }).join('');
  };
  window.validateAccount = async function(accId){
    var acc=accounts.find(function(a){return a.id===accId});
    setAccountCardMessage(accId,'正在校验...',false);
    var detailMsg=E('accountDetailMsg');
    if(detailMsg)detailMsg.innerHTML='<span style="color:var(--ink-soft)">正在校验...</span>';
    var d=await api('/api/accounts/'+encodeURIComponent(accId)+'/validate',{method:'POST'});
    await refreshAll();
    if(d.ok){
      setAccountCardMessage(accId,'校验通过：'+(d.real_email||acc&&acc.real_email||''),false);
      if(detailMsg)detailMsg.innerHTML='<span style="color:var(--green)">校验通过</span>';
    }else if(d.status==='warning'){
      setAccountCardMessage(accId,'校验超时，已保留旧数据：'+(d.error||'?'),false,true);
      if(detailMsg)detailMsg.innerHTML='<span style="color:#b77900">'+esc(d.error||'校验超时，已保留旧数据')+'</span>';
    }else{
      setAccountCardMessage(accId,'校验失败：'+(d.error||'?'),true);
      if(detailMsg)detailMsg.innerHTML='<span style="color:var(--red)">'+esc(d.error||'校验失败')+'</span>';
    }
  };
  window.createForAccount = async function(accId,count){
    setAccountCardMessage(accId,'正在创建 '+count+' 个...',false);
    var d=await apiSlow('/api/accounts/'+encodeURIComponent(accId)+'/create',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({count:count})});
    if(d.ok){
      setAccountCardMessage(accId,'成功创建 '+(d.created||0)+' 个',false);
      if(d.emails&&d.emails.length){
        aliasToolbarStatus('新创建 '+d.emails.length+' 个邮箱，已加入列表');
      }
    }else{
      setAccountCardMessage(accId,'创建失败：'+(d.error||'?'),true);
    }
    await refreshAll();
    if(curTab==='emails')await refreshEmails();
  };
  window.openAccountDetail = function(accId){
    var a=accounts.find(function(x){return x.id===accId});
    if(!a){toast('账号不存在',true);return}
    var h='<div class="modal-overlay" id="accountDetailModal" onclick="if(event.target===this)closeAccountDetail()"><div class="modal-box"><h3><i class="diamond"></i> 账号详情</h3><label style="font-family:var(--mono);font-size:11px;color:var(--ink-faint);letter-spacing:.2em;text-transform:uppercase">显示名称 / 备注</label><input type="text" id="renameInput" value="'+escAttr(accountDisplayName(a))+'"><div style="font-size:13px;line-height:1.9;color:var(--ink-soft);margin:4px 0 16px"><div><b>Apple ID:</b> '+esc(a.real_email||'-')+'</div><div><b>iCloud 邮箱:</b> '+esc(a.icloud_email||'-')+'</div><div><b>地区:</b> '+esc(a.host||'-')+'</div><div><b>状态:</b> '+esc(a.status||'-')+(a.last_error?' · '+esc(a.last_error):'')+'</div><div><b>别名:</b> '+(a.alias_total||0)+' / 活跃 '+(a.alias_active||0)+'</div></div><div style="display:flex;gap:10px;flex-wrap:wrap"><button class="btn btn-primary" onclick="renameAccount(&quot;'+escAttr(a.id)+'&quot;)">保存名称</button><button class="btn btn-outline" onclick="goAccountAliases(&quot;'+escAttr(a.id)+'&quot;)">查看别名</button><button class="btn btn-outline" onclick="goAccountInbox(&quot;'+escAttr(a.id)+'&quot;)">查看邮件</button><button class="btn btn-outline" onclick="validateAccount(&quot;'+escAttr(a.id)+'&quot;)">重新校验</button></div><div class="modal-actions"><button class="btn btn-outline" onclick="closeAccountDetail()">关闭</button></div><div class="modal-msg" id="accountDetailMsg"></div></div></div>';
    document.body.insertAdjacentHTML('beforeend',h);
  };
  window.closeAccountDetail = function(){var m=E('accountDetailModal');if(m)m.remove()};
  window.renameAccount = async function(accId){
    var name=E('renameInput').value.trim();
    if(!name){E('accountDetailMsg').innerHTML='<span style="color:var(--red)">名称不能为空</span>';return}
    var d=await api('/api/accounts/'+encodeURIComponent(accId)+'/rename',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:name})});
    if(d.ok){E('accountDetailMsg').innerHTML='<span style="color:var(--green)">已保存</span>';await refreshAll();setTimeout(closeAccountDetail,700);}
    else{E('accountDetailMsg').innerHTML='<span style="color:var(--red)">'+esc(d.error||'保存失败')+'</span>';}
  };
  window.goAccountAliases = function(accId){
    closeAccountDetail();
    document.querySelector('.nav-item[data-tab="emails"]').click();
    setTimeout(function(){var f=E('aliasFilter');if(f){f.value=accId;renderAliasTable();}},600);
  };
  window.goAccountInbox = function(accId){
    closeAccountDetail();
    document.querySelector('.nav-item[data-tab="inbox"]').click();
    setTimeout(function(){
      updateInboxAccountSelect({prefer:accId,skipLoad:true});
      var s=E('inboxAccount');
      if(s){
        s.value=accId;
        syncInboxSelectWidget(s);
        window.refreshInbox(false);
      }
    },80);
  };
  window.showAppPwdModal = function(accId){
    var acc=inboxAccountById(accId);
    var name=acc?accountDisplayName(acc):accId;
    var icloudEmail=(acc&&(acc.icloud_email||''))||'';
    if(!icloudEmail&&acc&&acc.real_email&&/(icloud\.com|me\.com|mac\.com)/.test(acc.real_email))icloudEmail=acc.real_email;
    var savedPwd=(acc&&(acc.app_password||''))||'';
    var fallbackUrl='https://account.apple.com/account/manage/section/security';
    var h=[
      '<div class="modal-overlay" id="appPwdModal">',
      '<div class="modal-box account-modal">',
      '<h3><i class="diamond"></i> 设置 iCloud 邮箱和 App 专用密码</h3>',
      '<p>账号: <b>'+esc(name)+'</b> (Apple ID: '+esc(acc?acc.real_email:'')+')</p>',
      '<div class="modal-note"><span>App 专用密码用于 IMAP 收件/取码，不是 Apple ID 登录密码。Apple 只在生成时显示一次。</span></div>',
      '<div class="modal-button-row"><button type="button" class="btn btn-primary" onclick="window.open(&quot;'+fallbackUrl+'&quot;,&quot;_blank&quot;)">打开 Apple ID 获取密码</button><button type="button" class="btn btn-outline" onclick="navigator.clipboard.writeText(E(&quot;icloudEmailInput&quot;).value).then(function(){toast(&quot;邮箱已复制&quot;)})">复制邮箱地址</button></div>',
      '<div class="modal-form">',
      '<label><span>iCloud 邮箱</span><input type="text" id="icloudEmailInput" value="'+escAttr(icloudEmail)+'" placeholder="xxx@icloud.com"></label>',
      '<label><span>App 专用密码</span><div class="password-field">',
      '<input type="password" id="appPwdInput" value="'+escAttr(savedPwd)+'" placeholder="xxxx-xxxx-xxxx-xxxx" autocomplete="new-password">',
      '<button class="btn btn-outline" type="button" onclick="toggleSavedAppPassword()">显示</button>',
      '<button class="btn btn-outline" type="button" onclick="copySavedAppPassword()">复制</button>',
      '</div></label>',
      '</div>',
      '<div class="modal-msg" id="appPwdMsg"></div>',
      '<div class="modal-actions"><button type="button" class="btn btn-outline" onclick="closeModal(&quot;appPwdModal&quot;)">取消</button><button type="button" class="btn btn-primary" id="btnSetPwd" onclick="setAppPassword(&quot;'+escAttr(accId)+'&quot;)">保存、测试并刷新收件箱</button></div>',
      '</div></div>'
    ].join('');
    closeModal('appPwdModal');
    document.body.insertAdjacentHTML('beforeend',h);
  };
  window.toggleSavedAppPassword = function(){
    var input=E('appPwdInput');
    if(!input)return;
    input.type=input.type==='password'?'text':'password';
  };
  window.copySavedAppPassword = function(){
    var input=E('appPwdInput');
    var val=input?input.value.trim():'';
    if(!val){toast('没有可复制的 App 专用密码',true);return}
    navigator.clipboard.writeText(val).then(function(){toast('App 专用密码已复制')});
  };
  function renderInboxError(accId,msg){
    var setup=accId&&accId!=='all'?'<br><br><button type="button" class="btn btn-primary" onclick="showAppPwdModal(&quot;'+escAttr(accId)+'&quot;)">设置收件箱</button>':'';
    E('inboxMsgs').innerHTML='<div class="empty"><div class="icon"></div>'+esc(msg||'连接失败')+setup+'</div>';
  }
  window.searchAliasMail = async function(){
    if(_inboxSearchBusy){inboxStatus('正在查询邮箱...');return;}
    var accId=E('inboxAccount').value;
    var alias=E('aliasSearchInput').value.trim();
    if(!accId){toast('请先选择账号',true);return}
    if(!alias){toast('请输入隐私邮箱地址',true);return}
    var requestSeq=++_inboxRequestSeq;
    _inboxSearchActive=true;
    _inboxSearchBusy=true;
    _inboxBusy=true;
    _inboxActiveAccId='search';
    inboxStatus('正在查询 '+alias+' ...');
    var limit=parseInt(E('inboxLimit').value)||20;
    try{
      var d=await api('/api/inbox/search?alias='+encodeURIComponent(alias)+'&limit='+limit,{timeout:120000});
      if(requestSeq!==_inboxRequestSeq)return;
      if(d.error){inboxStatus(d.error,true);return}
      renderInboxMsgs(d.emails||[],esc(alias)+' ('+(d.count||0)+' 封)',accId);
      inboxStatus('查件完成');
    }finally{
      _inboxSearchBusy=false;
      if(requestSeq===_inboxRequestSeq){
        _inboxBusy=false;
        _inboxActiveAccId='';
      }
    }
  };
  window.checkAliasMail = async function(){
    if(_inboxBusy)return;
    var accId=E('inboxAccount').value;
    if(!accId){E('inboxMsgs').innerHTML='<div class="empty"><div class="icon"></div>请先选择账号</div>';return}
    _inboxBusy=true;
    var limit=parseInt(E('inboxLimit').value)||20;
    var maxAliases=limit;
    E('inboxMsgs').innerHTML='<div class="empty"><div class="icon"></div>正在检查前 '+maxAliases+' 个隐私邮箱收件...</div>';
    var d=await apiSlow('/api/accounts/'+encodeURIComponent(accId)+'/alias-mail?force=1&limit='+limit+'&max_aliases='+maxAliases+'&mail_limit='+(Math.max(100,maxAliases||100)));
    _inboxBusy=false;
    if(d.error){renderInboxError(accId,d.error);return}
    var byAlias=d.by_alias||{};
    var aliasKeys=Object.keys(byAlias);
    if(!aliasKeys.length){E('inboxMsgs').innerHTML='<div class="empty"><div class="icon"></div>没有查到隐私邮箱收件</div>';return}
    var total=0,h='';
    aliasKeys.forEach(function(alias){var msgs=byAlias[alias]||[];total+=msgs.length;h+='<div style="padding:8px 14px;border-bottom:1px solid var(--rule);font-weight:600;font-size:13px;background:var(--paper-dim)">'+esc(alias)+' ('+msgs.length+' 封)</div>';msgs.forEach(function(m){h+='<div style="padding:6px 20px;border-bottom:1px solid var(--rule);font-size:12px;display:flex;justify-content:space-between;flex-wrap:wrap;gap:4px"><span><strong>'+esc(m.subject||'(无主题)')+'</strong></span><span style="color:var(--ink-soft)">'+esc(m.from||'').substring(0,30)+'</span><span style="color:var(--ink-faint);font-size:11px">'+(m.date||'').substring(0,19)+'</span></div>';});});
    E('inboxMsgs').innerHTML='<div style="font-size:11px;color:var(--ink-faint);padding:8px 14px;border-bottom:1px solid var(--rule)">共 '+aliasKeys.length+' 个别名收到 '+total+' 封邮件</div>'+h;
  };
  window.addAccount = async function(){
    var name=E('accNameInput').value.trim()||'未命名账号';
    var cookieEl=E('cookieInput');
    var rawCookies=(cookieEl&&cookieEl.value)||'';
    var cookies=normalizeCookieHeader(rawCookies);
    var cleaned=!!(rawCookies.trim()&&cookies&&cookies!==rawCookies.trim());
    if(cookieEl&&cookies)cookieEl.value=cookies;
    var host=E('hostInput').value||'icloud.com.cn';
    var icloudEmail=(E('addIcloudEmailInput')&&E('addIcloudEmailInput').value.trim())||'';
    var appPassword=(E('addAppPwdInput')&&E('addAppPwdInput').value.trim())||'';
    if(icloudEmail&&!/(@icloud\.com|@icloud\.com\.cn|@me\.com|@mac\.com)$/i.test(icloudEmail)){
      E('addAccMsg').innerHTML='<span style="color:var(--red)">iCloud 邮箱不能填 '+esc(icloudEmail)+'。这里要填 @icloud.com / @me.com / @mac.com 邮箱；不知道就先留空。</span>';
      return;
    }
    if(!cookies){E('addAccMsg').innerHTML='<span style="color:var(--red)">请粘贴 Cookie Header String</span>';return}
    var btn=E('btnAddAccount');btn.disabled=true;btn.textContent='校验中...';
    E('addAccMsg').innerHTML='<span style="color:var(--ink-soft)">'+(cleaned?'已自动清理 Cookie 外层引号，':'')+'正在按 '+esc(host)+' 校验 Cookie，首次可能需要 30-60 秒...</span>';
    var d=await api('/api/accounts/add',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:name,cookie_input:cookies,host:host,icloud_email:icloudEmail,app_password:appPassword}),timeout:90000});
    btn.disabled=false;btn.textContent='手动添加并校验';
    if(d.ok&&d.status==='active'){
      var imapText=d.imap_ok===true?'，收件箱可用':(d.imap_ok===false?'，但 IMAP 测试失败: '+esc(d.imap_error||'请稍后在收件箱设置里修改'):'');
      E('addAccMsg').innerHTML='<span style="color:'+(d.imap_ok===false?'#b36b00':'var(--green)')+'">添加成功! '+esc(d.real_email||'')+' ('+(d.alias_total||0)+' 别名)'+imapText+'</span>';
      if(d.imap_ok!==false)setTimeout(closeAddAccModal,1500);
      refreshAll();
    }
    else if(d.ok){E('addAccMsg').innerHTML='<span style="color:var(--red)">已保存但校验失败: '+esc(d.error||d.last_error||'请确认地区和 Cookie 是否正确')+'</span>';refreshAll();}
    else{E('addAccMsg').innerHTML='<span style="color:var(--red)">'+esc(d.error||'失败')+'</span>';}
  };
  window.toast = function(msg,isErr){
    var text=String(msg||'');
    var modalMsg=E('appPwdMsg')||E('addAccMsg')||E('accountDetailMsg');
    if(modalMsg&&document.querySelector('.modal-overlay')){
      modalMsg.innerHTML='<span style="color:'+(isErr?'var(--red)':'var(--green)')+'">'+esc(text)+'</span>';
      return;
    }
    if(curTab==='emails'){
      aliasToolbarStatus(text,!!isErr);
      return;
    }
    if(curTab==='inbox'){
      inboxStatus(text);
      return;
    }
    if(curTab==='batch'){
      var b=E('batchProgress');
      if(b)b.innerHTML='<div style="font-size:13px;color:'+(isErr?'var(--red)':'var(--green)')+'">'+esc(text)+'</div>';
      return;
    }
    var t=E('toast');
    if(t)t.classList.remove('show');
  };
  function stopInboxAutoRefresh(){
    if(_inboxAutoTimer){clearInterval(_inboxAutoTimer);_inboxAutoTimer=null;}
  }
  function startInboxAutoRefresh(){
    stopInboxAutoRefresh();
    if(curTab!=='inbox'||document.hidden)return;
    _inboxAutoTimer=setInterval(function(){
      if(curTab==='inbox'&&!document.hidden&&!_inboxBusy&&!inboxSearchMode())window.refreshInbox({refresh:true,background:true});
    },15000);
  }
  window.onAdminViewChanged=function(tab){
    if(tab==='inbox')startInboxAutoRefresh();
    else stopInboxAutoRefresh();
  };
  document.addEventListener('visibilitychange',function(){
    if(document.hidden)stopInboxAutoRefresh();
    else if(curTab==='inbox'){
      if(!inboxSearchMode())window.refreshInbox({refresh:true,background:true});
      startInboxAutoRefresh();
    }
  });
  var aliasSearchInput=E('aliasSearchInput');
  if(aliasSearchInput){
    aliasSearchInput.addEventListener('input',function(){if(!inboxSearchQuery())_inboxSearchActive=false;});
    aliasSearchInput.addEventListener('keydown',function(event){
      if(event.key==='Enter'){event.preventDefault();window.searchAliasMail();}
    });
  }
  window.refreshAll = async function(opts){
    opts=opts||{};
    if(_refreshBusy)return;
    _refreshBusy=true;
    try{
      var tab=curTab;
      var inboxSelected=E('inboxAccount')?E('inboxAccount').value:'';
      var aReq=api('/api/accounts');
      var sReq=api('/api/state');
      var a=await aReq;
      var s=await sReq;
      accounts=a.accounts||[];
      state=s;
      if(window.hmeStore){window.hmeStore.accounts=accounts;window.hmeStore.state=state;window.hmeStore.emails=emails;window.hmeStore.logs=logs;}
      renderSidebar();
      renderDashboard();
      if(tab==='emails'){
        if(opts.background&&emails.length){
          updateEmailFilter();
          renderAliasTable();
        }else{
          await refreshEmails();
          renderAliasTable();
        }
      }
      if(tab==='batch')renderBatchPanel();
      updateInboxAccountSelect({passive:!!opts.background,prefer:inboxSelected,accountsLoaded:true});
      if(tab==='codes'&&typeof renderCodeDesk==='function'&&!opts.background)renderCodeDesk();
    }finally{
      _refreshBusy=false;
    }
  };
  window.addEventListener('pickup-links-updated',function(){
    if(typeof refreshEmails!=='function')return;
    refreshEmails({background:true}).then(function(){if(curTab==='emails')renderAliasTable();});
  });
  (function(){
    var tabs={dashboard:1,emails:1,batch:1,codes:1,inbox:1,docs:1,logs:1};
    function rememberTab(tab){
      if(!tabs[tab])return;
      try{localStorage.setItem('icloudHmeTab',tab);}catch(_){}
      if(location.hash!=='#'+tab)history.replaceState(null,'','#'+tab);
    }
    function currentStoredTab(){
      var fromHash=(location.hash||'').replace(/^#/,'');
      if(tabs[fromHash])return fromHash;
      try{
        var stored=localStorage.getItem('icloudHmeTab');
        if(tabs[stored])return stored;
      }catch(_){}
      return '';
    }
    document.querySelectorAll('.nav-item[data-tab]').forEach(function(el){
      el.addEventListener('click',function(){rememberTab(this.dataset.tab);});
    });
    setTimeout(function(){
      var tab=currentStoredTab();
      if(tab&&tab!==curTab){
        var el=document.querySelector('.nav-item[data-tab="'+tab+'"]');
        if(el)el.click();
      }else{
        rememberTab(curTab||'dashboard');
      }
      setTimeout(function(){
        if(curTab==='emails'&&typeof refreshEmails==='function')refreshEmails();
      },150);
    },0);
  })();
})();
