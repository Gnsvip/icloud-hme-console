(function(){
  var statusEl = document.getElementById("status");
  var hostEl = document.getElementById("host");
  var outputEl = document.getElementById("cookieOutput");
  var generateBtn = document.getElementById("generate");
  var copyBtn = document.getElementById("copyCookie");
  var openBtn = document.getElementById("openIcloud");

  function setStatus(text, type){
    statusEl.textContent = text || "";
    statusEl.className = "status" + (type ? " " + type : "");
  }

  function cookieGetAll(filter){
    return new Promise(function(resolve){
      chrome.cookies.getAll(filter, function(items){ resolve(items || []); });
    });
  }

  function scoreCookie(cookie, host){
    var score = 0;
    var domain = String(cookie.domain || "");
    if (domain.indexOf(host) >= 0) score += 100;
    if (cookie.httpOnly) score += 5;
    if (cookie.secure) score += 3;
    score += Math.min(20, domain.length / 3);
    return score;
  }

  function normalizeCookieValue(value){
    var text = String(value == null ? "" : value).trim();
    if (text.length >= 2){
      var first = text.charAt(0);
      var last = text.charAt(text.length - 1);
      if ((first === '"' && last === '"') || (first === "'" && last === "'")){
        text = text.slice(1, -1);
      }
    }
    return text;
  }

  async function collectCookies(host){
    var domains = host === "icloud.com.cn"
      ? ["icloud.com.cn", "apple.com", "apple.com.cn"]
      : ["icloud.com", "apple.com"];
    var all = [];
    for (var i = 0; i < domains.length; i++){
      var items = await cookieGetAll({domain: domains[i]});
      all = all.concat(items);
    }
    var now = Date.now() / 1000;
    var byName = new Map();
    all.forEach(function(cookie){
      if (!cookie || !cookie.name || cookie.value == null) return;
      if (cookie.expirationDate && cookie.expirationDate < now) return;
      var old = byName.get(cookie.name);
      if (!old || scoreCookie(cookie, host) >= scoreCookie(old, host)){
        byName.set(cookie.name, cookie);
      }
    });
    var cookies = Array.from(byName.values()).sort(function(a,b){
      return String(a.name).localeCompare(String(b.name));
    });
    return {
      count: cookies.length,
      header: cookies.map(function(c){ return c.name + "=" + normalizeCookieValue(c.value); }).join("; ")
    };
  }

  async function generateCookies(){
    var host = hostEl.value || "icloud.com.cn";
    generateBtn.disabled = true;
    setStatus("正在读取 " + host + " Cookie...");
    try{
      var result = await collectCookies(host);
      if (!result.header || result.count < 3){
        outputEl.value = "";
        setStatus("没有读到足够的 iCloud Cookie。请先打开 iCloud 并完成登录。", "err");
        return;
      }
      outputEl.value = result.header;
      outputEl.focus();
      outputEl.select();
      setStatus("读取到 " + result.count + " 个 Cookie，已生成，可复制。", "ok");
    }catch(err){
      setStatus(err && err.message ? err.message : String(err), "err");
    }finally{
      generateBtn.disabled = false;
    }
  }

  async function copyCookies(){
    var text = outputEl.value || "";
    if (!text){
      setStatus("还没有 Cookie，先点“生成 Cookie”。", "err");
      return;
    }
    try{
      await navigator.clipboard.writeText(text);
      setStatus("已复制 Cookie，回后台粘贴即可。", "ok");
    }catch(_){
      outputEl.focus();
      outputEl.select();
      document.execCommand("copy");
      setStatus("已复制 Cookie，回后台粘贴即可。", "ok");
    }
  }

  function openIcloud(){
    var url = hostEl.value === "icloud.com" ? "https://www.icloud.com/" : "https://www.icloud.com.cn/";
    chrome.tabs.create({url: url});
  }

  openBtn.addEventListener("click", openIcloud);
  generateBtn.addEventListener("click", generateCookies);
  copyBtn.addEventListener("click", copyCookies);
})();
