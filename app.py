#!/usr/bin/env python3
"""Minimal HTTPS file-sharing server: upload -> get download link, browse & delete files."""

import os, secrets, time, pathlib, shutil, base64, hmac
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import json, mimetypes

UPLOAD_DIR = os.getenv("UPLOAD_DIR", "/data")
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8081"))
AUTH_USER = os.getenv("AUTH_USER", "admin")
AUTH_PASSWORD = os.getenv("AUTH_PASSWORD", "")

HTML_UPLOAD = r"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>File Share</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
  background:#0f172a;color:#e2e8f0;min-height:100vh;display:flex;flex-direction:column;align-items:center}
h1{margin:32px 0 6px;font-size:1.8rem;font-weight:600}
.sub{color:#94a3b8;margin-bottom:24px}
.upload-section{width:90%;max-width:600px}
.drop-zone{border:2px dashed #475569;border-radius:14px;
  padding:36px 20px;text-align:center;cursor:pointer;transition:.2s;
  background:rgba(30,41,59,.5)}
.drop-zone:hover,.drop-zone.dragover{border-color:#38bdf8;background:rgba(56,189,248,.06)}
.drop-zone p{color:#64748b;margin-top:10px;font-size:.9rem}
.drop-zone .icon{font-size:2rem;margin-bottom:2px}
input[type=file]{display:none}
.btn{display:inline-block;padding:9px 22px;border:none;border-radius:8px;font-size:.95rem;
  cursor:pointer;background:#0ea5e9;color:#fff;font-weight:500;transition:.15s;margin-top:12px}
.btn:hover{background:#0284c7}
.progress{display:none;height:5px;background:#1e293b;border-radius:3px;overflow:hidden;margin-top:12px}
.progress-bar{height:100%;width:0;background:#0ea5e9;border-radius:3px;transition:width .2s}
.result{display:none;background:#1e293b;border-radius:12px;padding:16px;margin-top:16px}
.result a{color:#38bdf8;word-break:break-all;font-size:.9rem}
.result .label{font-size:.8rem;color:#64748b;margin-bottom:4px}
.copy-btn{padding:3px 10px;font-size:.78rem;border:1px solid #334155;background:transparent;
  color:#e2e8f0;border-radius:5px;cursor:pointer;margin-top:6px}
.copy-btn:hover{background:#334155}
.copy-btn.ok{color:#4ade80;border-color:#166534}
.file-list-section{width:90%;max-width:600px;margin-top:32px;padding-bottom:40px}
.file-list-section h2{font-size:1.1rem;font-weight:600;margin-bottom:12px;color:#94a3b8}
.file-list-section h2 span{color:#64748b;font-weight:400}
.empty-msg{color:#475569;font-size:.9rem;text-align:center;padding:20px 0}
.file-item{display:flex;align-items:center;gap:10px;background:#1e293b;border-radius:10px;
  padding:12px 14px;margin-bottom:8px;transition:.15s}
.file-item:hover{background:#263348}
.file-info{flex:1;min-width:0}
.file-name{font-size:.9rem;font-weight:500;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.file-meta{font-size:.75rem;color:#64748b;margin-top:2px}
.file-actions{display:flex;gap:6px;flex-shrink:0}
.act-btn{padding:5px 10px;font-size:.75rem;border:1px solid #334155;background:transparent;
  color:#e2e8f0;border-radius:5px;cursor:pointer;white-space:nowrap}
.act-btn:hover{background:#334155}
.act-btn.copy:hover{border-color:#0ea5e9;color:#38bdf8}
.act-btn.copy.ok{color:#4ade80;border-color:#166534}
.act-btn.del:hover{border-color:#dc2626;color:#fca5a5}
.act-btn.del.confirming{background:#7f1d1d;border-color:#dc2626;color:#fff}
.footer{margin-top:auto;padding:16px;color:#475569;font-size:.75rem}
</style>
</head>
<body>
<h1>File Share</h1>
<p class="sub">Перетащите файл или нажмите для загрузки</p>
<div class="upload-section">
<div class="drop-zone" id="dz" onclick="document.getElementById('fi').click()">
<div class="icon">&#128228;</div>
<p>Файл будет доступен по уникальной ссылке</p>
</div>
<input type="file" id="fi">
<button class="btn" onclick="document.getElementById('fi').click()">Выбрать файл</button>
<div class="progress" id="pr"><div class="progress-bar" id="pb"></div></div>
<div class="result" id="res">
<div class="label">Ссылка для скачивания:</div>
<a id="link" target="_blank"></a><br>
<button class="copy-btn" onclick="copyLink()">Копировать</button>
</div>
</div>
<div class="file-list-section">
<h2>Загруженные файлы <span id="count"></span></h2>
<div id="fileList"></div>
</div>
<div class="footer">Срок хранения: 7 дней</div>
<script>
const dz=document.getElementById('dz'),fi=document.getElementById('fi'),
pr=document.getElementById('pr'),pb=document.getElementById('pb'),
res=document.getElementById('res'),link=document.getElementById('link');
dz.addEventListener('dragover',e=>{e.preventDefault();dz.classList.add('dragover')});
dz.addEventListener('dragleave',()=>dz.classList.remove('dragover'));
dz.addEventListener('drop',e=>{e.preventDefault();dz.classList.remove('dragover');
  if(e.dataTransfer.files.length)upload(e.dataTransfer.files[0])});
fi.addEventListener('change',()=>{if(fi.files.length)upload(fi.files[0])});
async function upload(file){
  pr.style.display='block';pb.style.width='0%';res.style.display='none';
  const fd=new FormData();fd.append('file',file);
  const xhr=new XMLHttpRequest();
  xhr.upload.onprogress=e=>{if(e.lengthComputable)pb.style.width=Math.round(e.loaded/e.total*100)+'%'};
  xhr.onload=()=>{
    pr.style.display='none';
    try{const d=JSON.parse(xhr.responseText);
      link.href=d.url;link.textContent=d.url;res.style.display='block';
    }catch(e){alert('Ошибка загрузки')}
    loadFiles();
  };
  xhr.onerror=()=>{pr.style.display='none';alert('Ошибка сети')};
  xhr.open('POST','/upload');xhr.send(fd);
  fi.value='';
}
function copyLink(){
  navigator.clipboard.writeText(link.href);
  const b=document.querySelector('.result .copy-btn');b.textContent='Скопировано!';
  b.classList.add('ok');setTimeout(()=>{b.textContent='Копировать';b.classList.remove('ok')},1500);
}
async function loadFiles(){
  const r=await fetch('/api/files');
  const data=await r.json();
  const list=document.getElementById('fileList');
  const count=document.getElementById('count');
  const files=data.files||[];
  count.textContent=files.length?'('+files.length+')':'';
  if(!files.length){list.innerHTML='<div class="empty-msg">Нет файлов</div>';return;}
  list.innerHTML=files.map(f=>{
    const size=f.size<1024?f.size+' B':
      f.size<1048576?(f.size/1024).toFixed(1)+' KB':
      (f.size/1048576).toFixed(1)+' MB';
    const d=new Date(f.ts*1000);
    const date=d.toLocaleDateString('ru')+' '+d.toLocaleTimeString('ru',{hour:'2-digit',minute:'2-digit'});
    return '<div class="file-item">'
      +'<div class="file-info">'
        +'<div class="file-name" title="'+esc(f.name)+'">'+esc(f.name)+'</div>'
        +'<div class="file-meta">'+size+' &middot; '+date+'</div>'
      +'</div>'
      +'<div class="file-actions">'
        +'<button class="act-btn copy" onclick="copyUrl(this,\''+esc(f.url)+'\')">Копировать</button>'
        +'<button class="act-btn del" data-token="'+esc(f.token)+'" onclick="confirmDel(this)">Удалить</button>'
      +'</div>'
    +'</div>';
  }).join('');
}
function esc(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');}
function copyUrl(btn,url){
  navigator.clipboard.writeText(url);
  btn.textContent='Скопировано!';btn.classList.add('ok');
  setTimeout(()=>{btn.textContent='Копировать';btn.classList.remove('ok')},1500);
}
function confirmDel(btn){
  if(btn.classList.contains('confirming')){deleteFile(btn);return;}
  btn.classList.add('confirming');btn.textContent='Точно?';
  const timer=setTimeout(()=>{btn.classList.remove('confirming');btn.textContent='Удалить';},3000);
  btn._timer=timer;
}
async function deleteFile(btn){
  clearTimeout(btn._timer);
  const token=btn.dataset.token;
  const item=btn.closest('.file-item');
  btn.textContent='...';btn.disabled=true;
  try{
    const r=await fetch('/api/delete/'+token,{method:'DELETE'});
    const d=await r.json();
    if(d.ok){item.style.opacity='0';item.style.transition='.3s';setTimeout(()=>item.remove(),300);
      const c=document.getElementById('count');
      const n=parseInt(c.textContent.replace(/\D/g,'')||'0')-1;
      c.textContent=n?'('+n+')':'';
      if(!n)loadFiles();
    }else{alert(d.error||'Ошибка');btn.textContent='Удалить';btn.disabled=false;btn.classList.remove('confirming');}
  }catch(e){alert('Ошибка сети');btn.textContent='Удалить';btn.disabled=false;btn.classList.remove('confirming');}
}
loadFiles();
</script>
</body>
</html>
"""

HTML_EXPIRED = r"""<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>File Share</title>
<style>body{font-family:sans-serif;background:#0f172a;color:#e2e8f0;
display:flex;align-items:center;justify-content:center;min-height:100vh}
.box{text-align:center;padding:40px}
h2{color:#f87171;margin-bottom:8px}p{color:#94a3b8}
a{color:#38bdf8}</style></head><body><div class="box">
<h2>Ссылка недействительна</h2><p>Файл удалён или срок действия истёк</p>
<a href="/">На главную</a></div></body></html>"""

META_FILE = os.path.join(UPLOAD_DIR, ".meta.json")
MAX_FILE_SIZE = 500 * 1024 * 1024
MAX_AGE_DAYS = 7


def load_meta():
    if os.path.exists(META_FILE):
        try:
            with open(META_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_meta(meta):
    with open(META_FILE, "w") as f:
        json.dump(meta, f, indent=2)


def cleanup(meta):
    now = time.time()
    to_del = [k for k, v in meta.items() if now - v.get("ts", 0) > MAX_AGE_DAYS * 86400]
    for k in to_del:
        fp = meta[k].get("path", "")
        if fp and os.path.exists(fp):
            os.remove(fp)
        del meta[k]
    if to_del:
        save_meta(meta)
    return len(to_del)


class Handler(BaseHTTPRequestHandler):
    def _authorized(self):
        if not AUTH_PASSWORD:
            return True
        header = self.headers.get("Authorization", "")
        if not header.startswith("Basic "):
            return False
        try:
            raw = base64.b64decode(header[6:]).decode("utf-8")
        except Exception:
            return False
        user, _, password = raw.partition(":")
        return hmac.compare_digest(user, AUTH_USER) and hmac.compare_digest(password, AUTH_PASSWORD)

    def _require_auth(self):
        if self._authorized():
            return True
        body = "Требуется авторизация".encode("utf-8")
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="File Share", charset="UTF-8"')
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        return False

    def do_GET(self):
        parsed = urlparse(self.path).path
        if not parsed.startswith("/d/") and not self._require_auth():
            return
        if parsed == "/" or parsed == "":
            self._send_html(HTML_UPLOAD)
        elif parsed == "/api/files":
            meta = load_meta()
            files = []
            for token, info in meta.items():
                files.append({
                    "token": token,
                    "name": info["name"],
                    "size": info.get("size", 0),
                    "ts": info.get("ts", 0),
                    "exists": os.path.exists(info.get("path", "")),
                })
            files.sort(key=lambda x: x["ts"], reverse=True)
            self._send_json({"files": files})
        elif parsed.startswith("/d/"):
            token = parsed[3:]
            meta = load_meta()
            info = meta.get(token)
            if not info or not os.path.exists(info["path"]):
                self._send_html(HTML_EXPIRED, 404)
                return
            self.send_response(200)
            mime = mimetypes.guess_type(info["name"])[0] or "application/octet-stream"
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(os.path.getsize(info["path"])))
            self.send_header("Content-Disposition", f'attachment; filename="{info["name"]}"')
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            with open(info["path"], "rb") as f:
                shutil.copyfileobj(f, self.wfile)
        else:
            self._send_html(HTML_EXPIRED, 404)

    def do_POST(self):
        if not self._require_auth():
            return
        parsed = urlparse(self.path).path
        if parsed != "/upload":
            self._send_json({"error": "not found"}, 404)
            return
        ctype = self.headers.get("Content-Type", "")
        boundary = None
        for part in ctype.split(";"):
            part = part.strip()
            if part.startswith("boundary="):
                boundary = part[9:].strip('"')
        if not boundary:
            self._send_json({"error": "no boundary"}, 400)
            return

        cl = int(self.headers.get("Content-Length", 0))
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
        safe_name = f"{token}{ext}"
        fpath = os.path.join(UPLOAD_DIR, safe_name)

        with open(fpath, "wb") as f:
            f.write(data)

        host = self.headers.get("Host", f"{HOST}:{PORT}")
        url = f"https://{host}/d/{token}"

        meta = load_meta()
        meta[token] = {"name": name, "path": fpath, "size": len(data), "ts": time.time()}
        save_meta(meta)
        cleanup(meta)

        self._send_json({"url": url, "name": name, "size": len(data)})

    def do_DELETE(self):
        if not self._require_auth():
            return
        parsed = urlparse(self.path).path
        if parsed.startswith("/api/delete/"):
            token = parsed[len("/api/delete/"):]
            meta = load_meta()
            info = meta.get(token)
            if not info:
                self._send_json({"error": "file not found"}, 404)
                return
            fp = info.get("path", "")
            if fp and os.path.exists(fp):
                os.remove(fp)
            del meta[token]
            save_meta(meta)
            self._send_json({"ok": True, "message": "deleted"})
            return

        if parsed.startswith("/d/"):
            token = parsed[3:]
            qs = parse_qs(urlparse(self.path).query)
            delete_key = qs.get("key", [None])[0]
            if not delete_key:
                self._send_json({"error": "missing delete key"}, 400)
                return
            meta = load_meta()
            info = meta.get(token)
            if not info:
                self._send_json({"error": "file not found"}, 404)
                return
            if info.get("delete_key") != delete_key:
                self._send_json({"error": "invalid delete key"}, 403)
                return
            fp = info.get("path", "")
            if fp and os.path.exists(fp):
                os.remove(fp)
            del meta[token]
            save_meta(meta)
            self._send_json({"ok": True, "message": "deleted"})
            return

        self._send_json({"error": "not found"}, 404)

    def _parse_multipart(self, body, boundary):
        parts = body.split(f"--{boundary}".encode())
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

    def _send_html(self, html, code=200):
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(html.encode())))
        self.end_headers()
        self.wfile.write(html.encode())

    def _send_json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        print(f"[{self.log_date_time_string()}] {args[0]}")


if __name__ == "__main__":
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    cleanup(load_meta())
    server = HTTPServer((HOST, PORT), Handler)
    print(f"File Share server: HTTP on {HOST}:{PORT}")
    print(f"Upload dir: {UPLOAD_DIR}")
    server.serve_forever()
