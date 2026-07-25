/* 公共鉴权与请求工具：所有页面引入。token 存 localStorage，fetch 自动带 Bearer，401 跳登录。 */
const Auth = {
  token: () => localStorage.getItem("dwpt_token"),
  user: () => { try { return JSON.parse(localStorage.getItem("dwpt_user") || "null"); } catch (e) { return null; } },
  save: (token, user) => { localStorage.setItem("dwpt_token", token); localStorage.setItem("dwpt_user", JSON.stringify(user)); },
  clear: () => { localStorage.removeItem("dwpt_token"); localStorage.removeItem("dwpt_user"); },
  loggedIn: () => !!localStorage.getItem("dwpt_token"),
};
function esc(s) { return (s == null ? "" : String(s)).replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c])); }
const _origFetch = window.fetch.bind(window);  // 保存原生 fetch，避免 window.fetch=authFetch 后递归
async function authFetch(url, opts = {}) {
  const t = Auth.token();
  opts.headers = Object.assign({}, opts.headers || {});
  if (t) opts.headers["Authorization"] = "Bearer " + t;
  if (opts.body && typeof opts.body === "object" && !(opts.body instanceof FormData)) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(opts.body);
  }
  const r = await _origFetch(url, opts);
  if (r.status === 401) {
    Auth.clear();
    location.href = "/login.html?next=" + encodeURIComponent(location.pathname + location.search);
    throw new Error("未登录");
  }
  return r;
}
function requireAuth() {
  if (!Auth.loggedIn()) {
    location.href = "/login.html?next=" + encodeURIComponent(location.pathname + location.search);
    return false;
  }
  return true;
}
function requireAdmin() {
  if (!requireAuth()) return false;
  if ((Auth.user() || {}).role !== "admin") {
    alert("需要管理员权限");
    location.href = "/chat.html";
    return false;
  }
  return true;
}
function logout() { Auth.clear(); location.href = "/login.html"; }
/* 渲染顶栏右侧用户条：当前用户名/角色 + 登出。elId 为容器元素 id */
function mountUserBar(elId) {
  const el = document.getElementById(elId);
  if (!el) return;
  const u = Auth.user();
  if (u) {
    el.innerHTML = `<span style="font-size:12px;color:#666;">${esc(u.username)} <span style="color:#aaa;">(${u.role})</span></span>
      <a href="#" onclick="logout();return false;" style="font-size:12px;color:#c0392b;text-decoration:none;margin-left:8px;">登出</a>`;
  }
}
