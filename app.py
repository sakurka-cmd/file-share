#!/usr/bin/env python3
"""File Share - multi-user HTTP file sharing server with roles and an admin panel."""

import os, secrets, time, pathlib, shutil, hmac, json, mimetypes, hashlib, html
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, quote

UPLOAD_DIR = os.getenv("UPLOAD_DIR", "/data")
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8081"))
AUTH_USER = os.getenv("AUTH_USER", "admin")
AUTH_PASSWORD = os.getenv("AUTH_PASSWORD", "")

USERS_FILE = os.path.join(UPLOAD_DIR, ".users.json")
META_FILE = os.path.join(UPLOAD_DIR, ".meta.json")
MAX_FILE_SIZE = 500 * 1024 * 1024
MAX_AGE_DAYS = 7
SESSION_TTL = 7 * 86400
COOKIE = "fs_session"
SESSIONS = {}

PERMS = ("upload", "delete", "view_all", "view_own")


def esc(s):
    return html.escape(str(s))


def _load(path, default):
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return default


def _save(path, obj):
    with open(path, "w") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)


def load_users():
    return _load(USERS_FILE, {})


def save_users(u):
    _save(USERS_FILE, u)


def load_meta():
    return _load(META_FILE, {})


def save_meta(m):
    _save(META_FILE, m)


def hash_password(pw):
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), salt, 200000)
    return salt.hex() + "$" + dk.hex()


def verify_password(pw, stored):
    try:
        salt_hex, dk_hex = stored.split("$", 1)
        salt = bytes.fromhex(salt_hex)
    except Exception:
        return False
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), salt, 200000)
    return hmac.compare_digest(dk.hex(), dk_hex)


def ensure_admin():
    users = load_users()
    if not users:
        users[AUTH_USER] = {
            "pw": hash_password(AUTH_PASSWORD or "admin"),
            "admin": True,
            "upload": True,
            "delete": True,
            "view_all": True,
            "view_own": True,
            "created": time.time(),
        }
        save_users(users)


def cleanup(meta):
    now = time.time()
    to_del = [k for k, v in meta.items() if now - v.get("ts", 0) > MAX_AGE_DAYS * 86400]
    for k in to_del:
        fp = meta[k].get("path", "")
        if fp and os.path.exists(fp):
            try:
                os.remove(fp)
            except OSError:
                pass
        del meta[k]
    if to_del:
        save_meta(meta)
    return len(to_del)


def prune_sessions():
    now = time.time()
    for k in [k for k, v in SESSIONS.items() if v["exp"] < now]:
        SESSIONS.pop(k, None)


STYLE = """
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
  background:#0f172a;color:#e2e8f0;min-height:100vh;display:flex;flex-direction:column;align-items:center}
a{color:#38bdf8}
.topbar{width:100%;background:#1e293b;border-bottom:1px solid #334155;padding:12px 20px;
  display:flex;align-items:center;gap:14px;justify-content:space-between}
.topbar .brand{font-weight:600}
.topbar .who{color:#94a3b8;font-size:.85rem;margin-right:10px}
.wrap{width:90%;max-width:680px;padding:28px 0 40px}
h1{margin:6px 0 18px;font-size:1.7rem}
.card{background:rgba(30,41,59,.6);border:1px solid #334155;border-radius:14px;padding:20px;margin-bottom:20px}
label{font-size:.9rem;color:#cbd5e1}
input[type=text],input[type=password]{width:100%;padding:9px 12px;border-radius:8px;border:1px solid #475569;
  background:#0f172a;color:#e2e8f0;font-size:.95rem;margin-top:4px}
input[type=file]{display:none}
.btn{display:inline-block;padding:9px 18px;border:none;border-radius:8px;font-size:.92rem;cursor:pointer;
  background:#0ea5e9;color:#fff;font-weight:500}
.btn:hover{background:#0284c7}
.btn.gray{background:#334155}
.btn.gray:hover{background:#475569}
.btn.del{background:#b91c1c}
.btn.del:hover{background:#dc2626}
.drop-zone{border:2px dashed #475569;border-radius:14px;padding:30px 20px;text-align:center;cursor:pointer;
  transition:.2s;background:rgba(15,23,42,.5)}
.drop-zone:hover,.drop-zone.dragover{border-color:#38bdf8;background:rgba(56,189,248,.06)}
.drop-zone p{color:#64748b;margin-top:8px;font-size:.87rem}
.progress{display:none;height:5px;background:#1e293b;border-radius:3px;overflow:hidden;margin-top:12px}
.progress-bar{height:100%;width:0;background:#0ea5e9;transition:width .2s}
.result{display:none;background:#0b1220;border-radius:12px;padding:14px;margin-top:14px}
.result a{word-break:break-all;font-size:.9rem}
.result .label{font-size:.8rem;color:#64748b;margin-bottom:4px}
.copy-btn{padding:4px 10px;font-size:.78rem;border:1px solid #334155;background:transparent;color:#e2e8f0;
  border-radius:5px;cursor:pointer;margin-top:6px}
.copy-btn:hover{background:#334155}
h2{font-size:1.05rem;color:#94a3b8;margin:6px 0 12px}
.empty-msg{color:#475569;font-size:.9rem;padding:16px 0}
.file-item{display:flex;align-items:center;gap:10px;background:#1e293b;border-radius:10px;padding:12px 14px;margin-bottom:8px}
.file-info{flex:1;min-width:0}
.file-name{font-size:.9rem;font-weight:500;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.file-meta{font-size:.75rem;color:#64748b;margin-top:2px}
.file-actions{display:flex;gap:6px;flex-shrink:0}
.act-btn{padding:5px 10px;font-size:.75rem;border:1px solid #334155;background:transparent;color:#e2e8f0;
  border-radius:5px;cursor:pointer;white-space:nowrap}
.act-btn:hover{background:#334155}
.act-btn.del:hover{border-color:#dc2626;color:#fca5a5}
.act-btn.confirming{background:#7f1d1d;border-color:#dc2626;color:#fff}
.msg{padding:10px 14px;border-radius:8px;margin-bottom:16px;font-size:.9rem}
.msg.ok{background:#064e3b;color:#a7f3d0}
.msg.err{background:#7f1d1d;color:#fecaca}
table{width:100%;border-collapse:collapse}
th,td{text-align:left;padding:8px 6px;border-bottom:1px solid #334155;font-size:.85rem;vertical-align:top}
th{color:#94a3b8;font-weight:500}
.chk{display:inline-flex;align-items:center;gap:4px;margin-right:8px;font-size:.8rem;color:#cbd5e1}
.chk input{width:auto}
.badge{background:#0ea5e9;color:#fff;border-radius:5px;font-size:.68rem;padding:1px 6px;margin-left:6px}
.small{font-size:.78rem;color:#64748b}
.footer{margin-top:auto;padding:16px;color:#475569;font-size:.75rem}
"""

LOGIN_HTML = """<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Вход - File Share</title><style>@@STYLE@@</style></head>
<body>
<div class="wrap" style="margin-top:8vh">
<h1>File Share</h1>
@@ERR@@
<div class="card">
<form method="post" action="/login">
<label>Логин<input type="text" name="username" autofocus autocomplete="username"></label>
<div style="height:10px"></div>
<label>Пароль<input type="password" name="password" autocomplete="current-password"></label>
<div style="height:14px"></div>
<button class="btn" type="submit">Войти</button>
</form>
</div>
</div>
<div class="footer">Powered by Caddy</div>
</body></html>"""

MAIN_HTML = """<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>File Share</title><style>@@STYLE@@</style></head>
<body>
<div class="topbar">
  <div class="brand">File Share</div>
  <div>
    <span class="who">@@USER@@</span>
    @@ADMINLINK@@
    <a class="btn gray" href="/logout">Выйти</a>
  </div>
</div>
<div class="wrap">
  <div id="uploadSection">
    <div class="card">
      <div class="drop-zone" id="dz" onclick="document.getElementById('fi').click()">
        <div style="font-size:2rem">&#128228;</div>
        <p>Перетащите файл или нажмите для загрузки (до 500 МБ)</p>
      </div>
      <input type="file" id="fi">
      <div style="margin-top:12px"><button class="btn" onclick="document.getElementById('fi').click()">Выбрать файл</button></div>
      <div class="progress" id="pr"><div class="progress-bar" id="pb"></div></div>
      <div class="result" id="res">
        <div class="label">Ссылка для скачивания:</div>
        <a id="link" target="_blank"></a><br>
        <button class="copy-btn" onclick="copyLink()">Копировать</button>
      </div>
    </div>
  </div>
  <h2>Файлы <span id="count"></span></h2>
  <div id="fileList"></div>
</div>
<div class="footer">Файлы хранятся 7 дней</div>
<script>
function esc(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;')}
function human(n){return n<1024?n+' B':n<1048576?(n/1024).toFixed(1)+' KB':(n/1048576).toFixed(1)+' MB'}
function date(ts){const d=new Date(ts*1000);return d.toLocaleDateString('ru')+' '+d.toLocaleTimeString('ru',{hour:'2-digit',minute:'2-digit'})}
async function api(url,opts){const r=await fetch(url,Object.assign({credentials:'same-origin'},opts||{}));if(r.status===401){location='/login';throw new Error('auth')}return r}
async function load(){
  const d=await (await api('/api/files')).json();
  document.getElementById('uploadSection').style.display=d.can.upload?'':'none';
  const list=document.getElementById('fileList');
  const files=d.files||[];
  document.getElementById('count').textContent=files.length?'('+files.length+')':'';
  if(!files.length){list.innerHTML='<div class="empty-msg">Нет файлов</div>';return}
  list.innerHTML=files.map(f=>{
    const url=location.origin+'/d/'+f.token;
    const owner=d.can.view_all?(' &middot; '+esc(f.owner||'-')):'';
    const del=f.can_delete?('<button class="act-btn del" data-token="'+esc(f.token)+'" onclick="askDel(this)">Удалить</button>'):'';
    return '<div class="file-item"><div class="file-info"><div class="file-name" title="'+esc(f.name)+'">'+esc(f.name)+'</div>'
      +'<div class="file-meta">'+human(f.size)+' &middot; '+date(f.ts)+owner+'</div></div>'
      +'<div class="file-actions"><button class="act-btn copy" onclick="copyUrl(this,\\''+url+'\\')">Копировать</button>'+del+'</div></div>';
  }).join('');
}
function copyUrl(btn,url){navigator.clipboard.writeText(url);btn.textContent='Скопировано!';setTimeout(()=>{btn.textContent='Копировать'},1500)}
function copyLink(){const l=document.getElementById('link');navigator.clipboard.writeText(l.href);const b=document.querySelector('.result .copy-btn');b.textContent='Скопировано!';setTimeout(()=>{b.textContent='Копировать'},1500)}
function askDel(btn){if(btn.classList.contains('confirming')){doDel(btn);return}btn.classList.add('confirming');btn.textContent='Точно?';btn._t=setTimeout(()=>{btn.classList.remove('confirming');btn.textContent='Удалить'},3000)}
async function doDel(btn){clearTimeout(btn._t);const t=btn.dataset.token;btn.textContent='...';btn.disabled=true;
  try{const r=await api('/api/delete/'+t,{method:'DELETE'});const d=await r.json();if(d.ok){load()}else{alert(d.error||'Ошибка');load()}}catch(e){}}
const dz=document.getElementById('dz'),fi=document.getElementById('fi'),pr=document.getElementById('pr'),pb=document.getElementById('pb'),res=document.getElementById('res'),link=document.getElementById('link');
dz.addEventListener('dragover',e=>{e.preventDefault();dz.classList.add('dragover')});
dz.addEventListener('dragleave',()=>dz.classList.remove('dragover'));
dz.addEventListener('drop',e=>{e.preventDefault();dz.classList.remove('dragover');if(e.dataTransfer.files.length)upload(e.dataTransfer.files[0])});
fi.addEventListener('change',()=>{if(fi.files.length)upload(fi.files[0])});
function upload(file){pr.style.display='block';pb.style.width='0%';res.style.display='none';
  const fd=new FormData();fd.append('file',file);const xhr=new XMLHttpRequest();
  xhr.upload.onprogress=e=>{if(e.lengthComputable)pb.style.width=Math.round(e.loaded/e.total*100)+'%'};
  xhr.onload=()=>{pr.style.display='none';
    if(xhr.status===401){location='/login';return}
    try{const d=JSON.parse(xhr.responseText);if(d.url){link.href=d.url;link.textContent=d.url;res.style.display='block'}else{alert(d.error||'Ошибка загрузки')}}catch(e){alert('Ошибка загрузки')}
    load()};
  xhr.onerror=()=>{pr.style.display='none';alert('Ошибка сети')};
  xhr.open('POST','/upload');xhr.send(fd);fi.value=''}
load();
</script>
</body></html>"""

ADMIN_HTML = """<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Админка - File Share</title><style>@@STYLE@@</style></head>
<body>
<div class="topbar">
  <div class="brand">File Share &middot; админка</div>
  <div><a class="btn gray" href="/">К файлам</a> <a class="btn gray" href="/logout">Выйти</a></div>
</div>
<div class="wrap" style="max-width:900px">
@@MSG@@
<div class="card">
<h2>Новый пользователь</h2>
<form method="post" action="/admin/users">
  <label>Логин<input type="text" name="username" required></label>
  <div style="height:8px"></div>
  <label>Пароль<input type="password" name="password" required></label>
  <div style="height:10px"></div>
  <div style="margin-bottom:12px">
    <label class="chk"><input type="checkbox" name="upload"> загружать</label>
    <label class="chk"><input type="checkbox" name="delete"> удалять</label>
    <label class="chk"><input type="checkbox" name="view_all"> список: все</label>
    <label class="chk"><input type="checkbox" name="view_own" checked> список: свои</label>
  </div>
  <button class="btn" type="submit">Создать</button>
</form>
</div>
<div class="card">
<h2>Пользователи</h2>
<table>
<tr><th>Логин</th><th>Права</th><th></th></tr>
@@ROWS@@
</table>
</div>
</div>
<div class="footer">Права: загрузка / удаление / список всех / список своих. Администратор имеет все права.</div>
</body></html>"""


def render_login(err=None):
    e = '<div class="msg err">Неверный логин или пароль</div>' if err else ""
    return LOGIN_HTML.replace("@@STYLE@@", STYLE).replace("@@ERR@@", e)


def render_main(username, admin):
    link = '<a class="btn gray" href="/admin">Админка</a>' if admin else ""
    return (MAIN_HTML.replace("@@STYLE@@", STYLE)
            .replace("@@USER@@", esc(username))
            .replace("@@ADMINLINK@@", link))


def render_admin(msg=None, err=None):
    users = load_users()
    rows = ""
    for name in sorted(users):
        u = users[name]
        if u.get("admin"):
            rows += ("<tr><td>%s<span class='badge'>admin</span></td>"
                     "<td><div class='small'>Все права (не редактируются)</div>"
                     "<form method='post' action='/admin/users/%s' style='margin-top:6px'>"
                     "<input type='password' name='password' placeholder='новый пароль (необязательно)'>"
                     "<div style='height:6px'></div><button class='btn' type='submit'>Сменить пароль</button></form></td>"
                     "<td></td></tr>") % (esc(name), quote(name))
            continue
        def chk(p):
            return "checked" if u.get(p) else ""
        rows += (
            "<tr><td>%s</td><td>"
            "<form method='post' action='/admin/users/%s'>"
            "<label class='chk'><input type='checkbox' name='upload' %s> загружать</label>"
            "<label class='chk'><input type='checkbox' name='delete' %s> удалять</label>"
            "<label class='chk'><input type='checkbox' name='view_all' %s> список: все</label>"
            "<label class='chk'><input type='checkbox' name='view_own' %s> список: свои</label>"
            "<div style='height:6px'></div>"
            "<input type='password' name='password' placeholder='новый пароль (необязательно)'>"
            "<div style='height:6px'></div><button class='btn' type='submit'>Сохранить</button></form>"
            "</td><td>"
            "<form method='post' action='/admin/users/%s/delete' onsubmit=\"return confirm('Удалить пользователя %s?')\">"
            "<button class='btn del' type='submit'>Удалить</button></form>"
            "</td></tr>"
        ) % (esc(name), quote(name), chk("upload"), chk("delete"), chk("view_all"), chk("view_own"), quote(name), esc(name))
    msgs = ""
    if msg:
        msgs += '<div class="msg ok">%s</div>' % esc(msg)
    if err:
        msgs += '<div class="msg err">%s</div>' % esc(err)
    return ADMIN_HTML.replace("@@STYLE@@", STYLE).replace("@@ROWS@@", rows).replace("@@MSG@@", msgs)


class Handler(BaseHTTPRequestHandler):
    # ---------- helpers ----------
    def _get_user(self):
        prune_sessions()
        raw = self.headers.get("Cookie", "")
        tok = None
        for part in raw.split(";"):
            k, _, v = part.strip().partition("=")
            if k == COOKIE:
                tok = v
        if not tok:
            return None
        s = SESSIONS.get(tok)
        if not s:
            return None
        s["exp"] = time.time() + SESSION_TTL
        return s["user"]

    def _cookie_for(self, user):
        tok = secrets.token_urlsafe(24)
        SESSIONS[tok] = {"user": user, "exp": time.time() + SESSION_TTL}
        secure = self.headers.get("X-Forwarded-Proto", "http") == "https"
        c = "%s=%s; HttpOnly; Path=/; SameSite=Lax; Max-Age=%d" % (COOKIE, tok, SESSION_TTL)
        if secure:
            c += "; Secure"
        return c

    def _clear_cookie(self):
        c = "%s=; HttpOnly; Path=/; SameSite=Lax; Max-Age=0" % COOKIE
        if self.headers.get("X-Forwarded-Proto", "http") == "https":
            c += "; Secure"
        return c

    def _redirect(self, loc, cookie=None):
        self.send_response(303)
        self.send_header("Location", loc)
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()

    def _read_form(self):
        try:
            cl = int(self.headers.get("Content-Length", 0))
        except ValueError:
            cl = 0
        body = self.rfile.read(cl).decode("utf-8", "replace")
        return {k: v[0] for k, v in parse_qs(body, keep_blank_values=True).items()}

    def _users(self):
        return load_users()

    def _is_admin(self, u):
        d = self._users().get(u, {})
        return bool(d.get("admin"))

    def _can(self, u, perm):
        d = self._users().get(u, {})
        if not d:
            return False
        return bool(d.get("admin")) or bool(d.get(perm))

    def _send_html(self, html_text, code=200):
        body = html_text.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # ---------- GET ----------
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        if path == "/d/" or path == "/d":
            self._send_html(HTML_EXPIRED, 404)
            return

        if path == "/login":
            self._send_html(render_login(err="err" in query))
            return

        if path == "/logout":
            self._redirect("/login", self._clear_cookie())
            return

        if path.startswith("/d/"):
            self._serve_download(path[3:])
            return

        user = self._get_user()
        if not user:
            self._redirect("/login")
            return

        if path == "/api/files":
            self._api_files(user)
            return

        if path == "/admin":
            if not self._is_admin(user):
                self._send_html(HTML_EXPIRED, 403)
                return
            self._send_html(render_admin(msg=query.get("msg", [None])[0], err=query.get("err", [None])[0]))
            return

        if path == "/" or path == "":
            self._send_html(render_main(user, self._is_admin(user)))
            return

        self._send_html(HTML_EXPIRED, 404)

    def _api_files(self, user):
        meta = load_meta()
        view_all = self._can(user, "view_all")
        view_own = self._can(user, "view_own")
        files = []
        for token, info in meta.items():
            owner = info.get("owner", "admin")
            if not (view_all or (view_own and owner == user)):
                continue
            can_delete = self._can(user, "delete") and (self._is_admin(user) or owner == user or view_all)
            files.append({
                "token": token,
                "name": info.get("name", "file"),
                "size": info.get("size", 0),
                "ts": info.get("ts", 0),
                "owner": owner,
                "can_delete": can_delete,
            })
        files.sort(key=lambda x: x["ts"], reverse=True)
        self._send_json({
            "user": user,
            "can": {
                "upload": self._can(user, "upload"),
                "delete": self._can(user, "delete"),
                "view_all": view_all,
                "view_own": view_own,
                "admin": self._is_admin(user),
            },
            "files": files,
        })

    def _serve_download(self, token):
        meta = load_meta()
        info = meta.get(token)
        if not info or not os.path.exists(info.get("path", "")):
            self._send_html(HTML_EXPIRED, 404)
            return
        self.send_response(200)
        mime = mimetypes.guess_type(info["name"])[0] or "application/octet-stream"
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(os.path.getsize(info["path"])))
        self.send_header("Content-Disposition", 'attachment; filename="%s"' % info["name"])
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        with open(info["path"], "rb") as f:
            shutil.copyfileobj(f, self.wfile)

    # ---------- POST ----------
    def do_POST(self):
        path = urlparse(self.path).path

        if path == "/login":
            form = self._read_form()
            name = (form.get("username") or "").strip()
            pw = form.get("password") or ""
            u = self._users().get(name)
            if u and verify_password(pw, u.get("pw", "")):
                self._redirect("/", self._cookie_for(name))
            else:
                self._redirect("/login?err=1")
            return

        if path == "/logout":
            self._redirect("/login", self._clear_cookie())
            return

        user = self._get_user()
        if not user:
            self._send_json({"error": "unauthorized"}, 401)
            return

        if path == "/upload":
            if not self._can(user, "upload"):
                self._send_json({"error": "forbidden"}, 403)
                return
            self._handle_upload(user)
            return

        if path == "/admin/users":
            if not self._is_admin(user):
                self._send_html(HTML_EXPIRED, 403)
                return
            self._admin_create()
            return

        if path.startswith("/admin/users/"):
            if not self._is_admin(user):
                self._send_html(HTML_EXPIRED, 403)
                return
            rest = path[len("/admin/users/"):]
            if rest.endswith("/delete"):
                self._admin_delete(rest[:-len("/delete")])
            else:
                self._admin_update(rest)
            return

        self._send_json({"error": "not found"}, 404)

    def _handle_upload(self, user):
        ctype = self.headers.get("Content-Type", "")
        boundary = None
        for part in ctype.split(";"):
            part = part.strip()
            if part.startswith("boundary="):
                boundary = part[9:].strip('"')
        if not boundary:
            self._send_json({"error": "no boundary"}, 400)
            return
        try:
            cl = int(self.headers.get("Content-Length", 0))
        except ValueError:
            cl = 0
        if cl > MAX_FILE_SIZE:
            self._send_json({"error": "file too large (max 500MB)"}, 413)
            return
        body = self.rfile.read(cl)
        name, data = self._parse_multipart(body, boundary)
        if not data:
            self._send_json({"error": "empty file"}, 400)
            return
        token = secrets.token_urlsafe(8)
        ext = pathlib.Path(name).suffix if name else ""
        fpath = os.path.join(UPLOAD_DIR, token + ext)
        with open(fpath, "wb") as f:
            f.write(data)
        host = self.headers.get("Host", "%s:%d" % (HOST, PORT))
        url = "https://%s/d/%s" % (host, token)
        meta = load_meta()
        meta[token] = {"name": name, "path": fpath, "size": len(data), "ts": time.time(), "owner": user}
        save_meta(meta)
        cleanup(meta)
        self._send_json({"url": url, "name": name, "size": len(data)})

    def _admin_create(self):
        form = self._read_form()
        name = (form.get("username") or "").strip()
        pw = form.get("password") or ""
        import re
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,32}", name or ""):
            self._redirect("/admin?err=" + quote("Недопустимый логин (A-Za-z0-9_.-, до 32 символов)"))
            return
        users = load_users()
        if name in users:
            self._redirect("/admin?err=" + quote("Пользователь уже существует"))
            return
        if not pw:
            self._redirect("/admin?err=" + quote("Нужен пароль"))
            return
        users[name] = {
            "pw": hash_password(pw),
            "admin": False,
            "upload": form.get("upload") == "on",
            "delete": form.get("delete") == "on",
            "view_all": form.get("view_all") == "on",
            "view_own": form.get("view_own") == "on",
            "created": time.time(),
        }
        save_users(users)
        self._redirect("/admin?msg=" + quote("Пользователь %s создан" % name))

    def _admin_update(self, name):
        users = load_users()
        if name not in users:
            self._redirect("/admin?err=" + quote("Пользователь не найден"))
            return
        form = self._read_form()
        u = users[name]
        pw = form.get("password") or ""
        if pw:
            u["pw"] = hash_password(pw)
        if not u.get("admin"):
            u["upload"] = form.get("upload") == "on"
            u["delete"] = form.get("delete") == "on"
            u["view_all"] = form.get("view_all") == "on"
            u["view_own"] = form.get("view_own") == "on"
        save_users(users)
        self._redirect("/admin?msg=" + quote("Сохранено: %s" % name))

    def _admin_delete(self, name):
        users = load_users()
        if name not in users:
            self._redirect("/admin?err=" + quote("Пользователь не найден"))
            return
        if users[name].get("admin"):
            self._redirect("/admin?err=" + quote("Нельзя удалить администратора"))
            return
        del users[name]
        save_users(users)
        self._redirect("/admin?msg=" + quote("Удалён: %s" % name))

    def _parse_multipart(self, body, boundary):
        parts = body.split(("--%s" % boundary).encode())
        for part in parts[1:]:
            if b"--" in part[:4]:
                part = part[: part.index(b"--")]
            if b"\r\n\r\n" in part:
                header, data = part.split(b"\r\n\r\n", 1)
                data = data.rstrip(b"\r\n")
                fn = "file"
                for line in header.split(b"\r\n"):
                    if b'filename="' in line:
                        fn = line.split(b'filename="')[1].split(b'"')[0].decode("utf-8", errors="replace")
                        break
                return fn, data
        return None, None

    # ---------- DELETE ----------
    def do_DELETE(self):
        user = self._get_user()
        if not user:
            self._send_json({"error": "unauthorized"}, 401)
            return
        path = urlparse(self.path).path
        if not path.startswith("/api/delete/"):
            self._send_json({"error": "not found"}, 404)
            return
        if not self._can(user, "delete"):
            self._send_json({"error": "forbidden"}, 403)
            return
        token = path[len("/api/delete/"):]
        meta = load_meta()
        info = meta.get(token)
        if not info:
            self._send_json({"error": "file not found"}, 404)
            return
        owner = info.get("owner", "admin")
        if not (self._is_admin(user) or owner == user or self._can(user, "view_all")):
            self._send_json({"error": "forbidden"}, 403)
            return
        fp = info.get("path", "")
        if fp and os.path.exists(fp):
            try:
                os.remove(fp)
            except OSError:
                pass
        del meta[token]
        save_meta(meta)
        self._send_json({"ok": True, "message": "deleted"})

    def log_message(self, fmt, *args):
        print("[%s] %s" % (self.log_date_time_string(), args[0]))


HTML_EXPIRED = """<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>File Share</title>
<style>body{font-family:sans-serif;background:#0f172a;color:#e2e8f0;display:flex;
align-items:center;justify-content:center;min-height:100vh}.box{text-align:center;padding:40px}
h2{color:#f87171;margin-bottom:8px}p{color:#94a3b8}a{color:#38bdf8}</style></head>
<body><div class="box"><h2>Недоступно</h2><p>Ссылка недействительна, нет прав или страница не найдена</p>
<a href="/">На главную</a></div></body></html>"""


if __name__ == "__main__":
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    ensure_admin()
    cleanup(load_meta())
    server = HTTPServer((HOST, PORT), Handler)
    print("File Share server: HTTP on %s:%d" % (HOST, PORT))
    print("Upload dir: %s" % UPLOAD_DIR)
    server.serve_forever()
