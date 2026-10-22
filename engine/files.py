#!/usr/bin/env python3
"""鲸鲸文件箱 —— 手机浏览器 ⇄ 容器工作区 的文件管理器。

功能：浏览/新建/重命名/删除、上传文件、上传整个文件夹、zip 自动解压、
      在线预览（图片/文本）、整目录打包下载。
只监听 127.0.0.1；所有路径都被限制在 ROOT 之内。
"""
import io
import json
import mimetypes
import os
import re
import shutil
import tempfile
import time
import zipfile
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, unquote, urlparse

ROOT = os.environ.get(
    "ROOT", "/root/Documents/deepseek-harness/default-workspace"
)
PORT = int(os.environ.get("PORT", "8791"))
VERSION = "3"
STARTED = time.time()
BRIDGE = "http://127.0.0.1:3090"
BRIDGE_HEADERS = os.environ.get("WHALE_FILES_BRIDGE_HEADERS", "/root/.dsh/.bridge_headers")
TEXT_EXT = {
    ".txt", ".md", ".json", ".jsonl", ".yaml", ".yml", ".toml", ".ini", ".cfg",
    ".py", ".js", ".mjs", ".ts", ".tsx", ".jsx", ".c", ".h", ".cpp", ".rs",
    ".go", ".java", ".kt", ".sh", ".bash", ".zsh", ".css", ".html", ".xml",
    ".csv", ".log", ".sql", ".gitignore", ".env", ".yml",
}
IMG_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".svg", ".heic"}


# ─────────────────────────── 路径工具 ───────────────────────────

def resolve_in_root(rel: str) -> str:
    rel = (rel or "").strip().lstrip("/")
    target = os.path.realpath(os.path.join(ROOT, rel))
    if target != ROOT and not target.startswith(ROOT + os.sep):
        raise PermissionError("path outside root")
    return target


def rel_of(path: str) -> str:
    return os.path.relpath(path, ROOT).replace(os.sep, "/").replace(".", "", 1) \
        if path != ROOT else ""


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"


def safe_segment(name: str) -> str:
    name = name.replace("\\", "/").split("/")[-1]
    name = re.sub(r"[\x00-\x1f<>:\"|?*]", "_", name).strip(" .")
    return name or "unnamed"


def unique_path(directory: str, name: str) -> str:
    base, ext = os.path.splitext(name)
    candidate = os.path.join(directory, name)
    i = 1
    while os.path.exists(candidate):
        candidate = os.path.join(directory, f"{base}-{i}{ext}")
        i += 1
    return candidate


def zip_member_name(info: zipfile.ZipInfo) -> str:
    """处理国产压缩工具的 GBK 文件名。"""
    if info.flag_bits & 0x800:
        return info.filename
    try:
        return info.filename.encode("cp437").decode("gbk")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return info.filename


def looks_like_zip(path: str, name: str) -> bool:
    if name.lower().endswith(".zip"):
        return True
    try:
        with open(path, "rb") as f:
            head = f.read(4)
        return head[:2] == b"PK"
    except OSError:
        return False


def extract_zip(zip_path: str, dest: str, stem: str = "") -> int:
    """解压到 dest/<stem>/ 里（永远建一层以此命名的文件夹），防 zip-slip。

    若压缩包内恰好只有一个与 stem 同名的顶层目录，去掉这一层避免同名双套。
    """
    count = 0
    with zipfile.ZipFile(zip_path) as zf:
        members = [(zip_member_name(i), i) for i in zf.infolist()]
        out_dir = os.path.join(dest, stem or "解压")
        if os.path.isfile(out_dir):
            out_dir = unique_path(os.path.dirname(out_dir), os.path.basename(out_dir) + "_解压")
        os.makedirs(out_dir, exist_ok=True)
        real_out = os.path.realpath(out_dir)
        for name, info in members:
            if name.endswith("/"):
                continue
            parts = [safe_segment(x) for x in name.split("/") if x not in ("", ".", "..")]
            if not parts:
                continue
            if stem and parts[0] == stem and len(parts) > 1:
                parts = parts[1:]
            target = os.path.join(out_dir, *parts)
            if not os.path.realpath(target).startswith(real_out + os.sep):
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst, 1 << 20)
            count += 1
    return count


def parse_multipart(body_path: str, boundary: bytes):
    """从磁盘上的 body 里逐个产出 (filename, headers, temp_file_path, size)。"""
    delim = b"--" + boundary
    sep = b"\r\n" + delim
    buf = b""

    with open(body_path, "rb") as f:
        while True:
            chunk = f.read(1 << 16)
            if not chunk:
                return
            buf += chunk
            i = buf.find(delim)
            if i >= 0:
                buf = buf[i + len(delim):]
                break

        while True:
            while len(buf) < 2:
                more = f.read(1 << 16)
                if not more:
                    return
                buf += more
            if buf.startswith(b"--"):
                return
            if buf.startswith(b"\r\n"):
                buf = buf[2:]
            while b"\r\n\r\n" not in buf:
                more = f.read(1 << 16)
                if not more:
                    return
                buf += more
            hi = buf.find(b"\r\n\r\n")
            head = buf[:hi].decode("utf-8", "replace")
            buf = buf[hi + 4:]

            m = re.search(r'filename="([^"]*)"', head)
            filename = m.group(1) if m else None
            out = tempfile.NamedTemporaryFile(delete=False, dir="/tmp", suffix=".part")
            size = 0
            while True:
                j = buf.find(sep)
                if j >= 0:
                    out.write(buf[:j])
                    size += j
                    buf = buf[j + len(sep):]
                    break
                keep = len(sep) - 1
                if len(buf) > keep:
                    out.write(buf[:-keep])
                    size += len(buf) - keep
                    buf = buf[-keep:]
                more = f.read(1 << 16)
                if not more:
                    out.write(buf)
                    size += len(buf)
                    buf = b""
                    out.close()
                    if filename is not None:
                        yield filename, head, out.name, size
                    os.unlink(out.name)
                    return
                buf += more
            out.close()
            if filename is not None:
                yield filename, head, out.name, size
            os.unlink(out.name)


# ───────────────────────────── 页面 ─────────────────────────────

PAGE = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "page.html"), encoding="utf-8").read()



def make_zip(target: str) -> str:
    """把文件/目录打成临时 zip，返回临时文件路径。"""
    base = os.path.basename(os.path.normpath(target)) or "workspace"
    out = os.path.join("/tmp", unique_name(base + ".zip"))
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        if os.path.isfile(target):
            zf.write(target, base)
        else:
            for cur, dirs, files in os.walk(target):
                dirs[:] = [x for x in dirs if x not in ("node_modules", ".git")]
                for f in files:
                    full = os.path.join(cur, f)
                    arc = os.path.join(base, os.path.relpath(full, target))
                    try:
                        zf.write(full, arc)
                    except OSError:
                        pass
    return out


def unique_name(name: str) -> str:
    path = os.path.join("/tmp", name)
    base, ext = os.path.splitext(name)
    i = 1
    while os.path.exists(path):
        path = os.path.join("/tmp", f"{base}-{i}{ext}")
        i += 1
    return os.path.basename(path)


def export_to_phone(path: str) -> tuple:
    """调设备桥把容器里的文件投到手机 Download/DSHA。返回 (ok, message)。"""
    try:
        with open(BRIDGE_HEADERS, encoding="utf-8") as f:
            line = f.read().strip().splitlines()[0]
        token = line.split(":", 1)[1].strip()
    except OSError as e:
        return False, f"读不到桥凭据：{e}"
    q = urllib.parse.urlencode({"path": path})
    req = urllib.request.Request(f"{BRIDGE}/app/export?{q}", headers={"X-Token": token})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            body = r.read().decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        return False, f"调用设备桥失败：{type(e).__name__}: {e}"
    try:
        payload = json.loads(body)
        result = str(payload.get("result", body))
    except json.JSONDecodeError:
        result = body
    if result.startswith("OK"):
        return True, result
    return False, result


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "whale-files"

    def log_message(self, fmt, *args):
        print("%s %s" % (self.address_string(), fmt % args), flush=True)

    # ── 基础响应 ──
    def send_body(self, code, data, ctype="application/json; charset=utf-8", extra=None):
        extra = {"Cache-Control": "no-store, must-revalidate", **(extra or {})}
        if isinstance(data, str):
            data = data.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def send_file(self, path, download_name=None):
        size = os.path.getsize(path)
        ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        if download_name:
            ctype = "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(size))
        self.send_header("Cache-Control", "no-store")
        if download_name:
            self.send_header(
                "Content-Disposition",
                f"attachment; filename*=UTF-8''{quote(download_name)}",
            )
        self.end_headers()
        with open(path, "rb") as f:
            shutil.copyfileobj(f, self.wfile, 1 << 20)

    def json(self, obj, code=200):
        self.send_body(code, json.dumps(obj, ensure_ascii=False))

    def read_json(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    # ── GET ──
    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        p = q.get("p", [""])[0]
        try:
            if u.path in ("/", "/index.html"):
                self.send_body(200, PAGE, "text/html; charset=utf-8")
            elif u.path == "/api/ping":
                self.json({"ok": True, "version": VERSION, "root": ROOT,
                           "uptime": int(time.time() - STARTED),
                           "pid": os.getpid()})
            elif u.path == "/api/list":
                self.api_list(p)
            elif u.path == "/api/preview":
                self.api_preview(p)
            elif u.path == "/api/raw":
                target = resolve_in_root(p)
                if not os.path.isfile(target):
                    self.json({"ok": False, "error": "文件不存在"}, 404)
                    return
                self.send_file(target, os.path.basename(target) if q.get("dl") else None)
            elif u.path == "/api/zip":
                self.api_zip(p)
            else:
                self.json({"ok": False, "error": "not found"}, 404)
        except PermissionError:
            self.json({"ok": False, "error": "路径越界"}, 403)
        except Exception as e:  # noqa: BLE001
            self.json({"ok": False, "error": f"{type(e).__name__}: {e}"}, 500)

    def api_list(self, p):
        d = resolve_in_root(p)
        if not os.path.isdir(d):
            self.json({"ok": False, "error": "不是目录"}, 400)
            return
        entries = []
        with os.scandir(d) as it:
            for e in it:
                try:
                    is_dir = e.is_dir()
                    size = 0 if is_dir else e.stat().st_size
                    count = sum(1 for _ in os.scandir(e.path)) if is_dir else 0
                except OSError:
                    continue
                ext = os.path.splitext(e.name)[1].lower()
                entries.append({
                    "name": e.name,
                    "dir": is_dir,
                    "size": size,
                    "size_h": human(size),
                    "count": count,
                    "img": ext in IMG_EXT,
                    "text": ext in TEXT_EXT,
                })
        entries.sort(key=lambda x: (not x["dir"], x["name"].lower()))
        self.json({"ok": True, "p": p, "abs": d, "root": ROOT, "entries": entries})

    def api_preview(self, p):
        target = resolve_in_root(p)
        if not os.path.isfile(target):
            self.json({"ok": False, "error": "文件不存在"}, 404)
            return
        ext = os.path.splitext(target)[1].lower()
        if ext in IMG_EXT:
            self.json({"ok": True, "kind": "image"})
        elif ext in TEXT_EXT or os.path.getsize(target) < 200_000:
            with open(target, "rb") as f:
                raw = f.read(200_000)
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                text = raw.decode("gbk", "replace")
            self.json({"ok": True, "kind": "text", "text": text})
        else:
            self.json({"ok": True, "kind": "binary"})

    def api_zip(self, p):
        target = resolve_in_root(p)
        if not os.path.exists(target):
            self.json({"ok": False, "error": "不存在"}, 404)
            return
        tmp = make_zip(target)
        name = os.path.basename(tmp)
        self.send_file(tmp, name)
        os.unlink(tmp)

    # ── POST ──
    def do_POST(self):
        u = urlparse(self.path)
        try:
            if u.path == "/upload":
                self.upload()
            elif u.path == "/api/mkdir":
                body = self.read_json()
                os.makedirs(resolve_in_root(body["p"]), exist_ok=True)
                self.json({"ok": True})
            elif u.path == "/api/rename":
                body = self.read_json()
                src = resolve_in_root(body["p"])
                dst = resolve_in_root(body["to"])
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                os.rename(src, dst)
                self.json({"ok": True})
            elif u.path == "/api/export":
                body = self.read_json()
                src = resolve_in_root(body["p"])
                if not os.path.exists(src):
                    self.json({"ok": False, "error": "不存在"}, 404)
                    return
                if os.path.isdir(src):
                    zipped = make_zip(src)
                    try:
                        ok, msg = export_to_phone(zipped)
                    finally:
                        try: os.unlink(zipped)
                        except OSError: pass
                else:
                    ok, msg = export_to_phone(src)
                self.json({"ok": ok, "message": msg,
                           "name": os.path.basename(os.path.normpath(src))})
            elif u.path == "/api/move":
                body = self.read_json()
                src = resolve_in_root(body["p"])
                dst = resolve_in_root(body["to"])
                if not os.path.exists(src):
                    self.json({"ok": False, "error": "源不存在"}, 404)
                elif src == ROOT:
                    self.json({"ok": False, "error": "不能移动根目录"}, 400)
                elif os.path.exists(dst):
                    self.json({"ok": False, "error": "目标已存在"}, 409)
                elif not os.path.isdir(os.path.dirname(dst)):
                    self.json({"ok": False, "error": "目标目录不存在"}, 400)
                else:
                    os.rename(src, dst)
                    self.json({"ok": True, "to": os.path.relpath(dst, ROOT)})
            elif u.path == "/api/delete":
                body = self.read_json()
                target = resolve_in_root(body["p"])
                if target == ROOT:
                    self.json({"ok": False, "error": "不能删根目录"}, 400)
                elif os.path.isdir(target):
                    shutil.rmtree(target)
                    self.json({"ok": True})
                else:
                    os.unlink(target)
                    self.json({"ok": True})
            else:
                self.json({"ok": False, "error": "not found"}, 404)
        except PermissionError:
            self.json({"ok": False, "error": "路径越界"}, 403)
        except Exception as e:  # noqa: BLE001
            self.json({"ok": False, "error": f"{type(e).__name__}: {e}"}, 500)

    def upload(self):
        ctype = self.headers.get("Content-Type", "")
        m = re.search(r'boundary="?([^";]+)"?', ctype)
        if not m or "multipart/form-data" not in ctype:
            self.json({"ok": False, "error": "需要 multipart/form-data"}, 400)
            return
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            self.json({"ok": False, "error": "空请求"}, 400)
            return

        body = tempfile.NamedTemporaryFile(delete=False, dir="/tmp", suffix=".body")
        remaining = length
        while remaining > 0:
            chunk = self.rfile.read(min(1 << 16, remaining))
            if not chunk:
                break
            body.write(chunk)
            remaining -= len(chunk)
        body.close()

        cwd_rel = ""
        saved = []
        try:
            for filename, head, tmp, size in parse_multipart(body.name, m.group(1).encode()):
                if filename == "" and re.search(r'name="dir"', head):
                    with open(tmp, "rb") as f:
                        cwd_rel = f.read().decode("utf-8", "replace")
                    continue
                if filename is None:
                    continue
                rel = filename.replace("\\", "/")
                rel = "/".join(safe_segment(x) for x in rel.split("/") if x not in ("", ".", ".."))
                base_dir = resolve_in_root(cwd_rel)
                os.makedirs(base_dir, exist_ok=True)
                target = resolve_in_root(os.path.join(cwd_rel, rel) if cwd_rel else rel)
                os.makedirs(os.path.dirname(target), exist_ok=True)
                if looks_like_zip(tmp, rel) and size > 22:
                    shutil.copyfile(tmp, target)
                    try:
                        n = extract_zip(target, os.path.dirname(target),
                                        os.path.splitext(os.path.basename(rel))[0] or "解压")
                        if n == 0:
                            saved.append({"name": os.path.basename(rel),
                                          "size_h": "压缩包内没有文件，已保留原包"})
                        else:
                            os.unlink(target)
                            saved.append({"name": os.path.basename(rel), "size_h": f"解压出 {n} 个文件"})
                    except Exception as e:  # noqa: BLE001 解不了就留原件
                        saved.append({"name": rel, "size_h": human(size) + "（非标准压缩包，已原样保存）"})
                        print("zip 解压失败:", e, flush=True)
                else:
                    if os.path.exists(target):
                        target = unique_path(os.path.dirname(target), os.path.basename(target))
                    shutil.copyfile(tmp, target)
                    saved.append({"name": rel, "size_h": human(size)})
        finally:
            os.unlink(body.name)

        if not saved:
            self.json({"ok": False, "error": "没收到文件"}, 400)
            return
        self.json({"ok": True, **saved[-1], "saved": saved})


def cleanup_stale_temps(max_age=3600):
    """清掉中断上传留下的临时文件。"""
    now = time.time()
    for name in os.listdir("/tmp"):
        if not (name.startswith("upload-") or name.endswith(".part") or name.endswith(".body")):
            continue
        p = os.path.join("/tmp", name)
        try:
            if now - os.path.getmtime(p) > max_age:
                os.unlink(p)
        except OSError:
            pass


if __name__ == "__main__":
    os.makedirs(ROOT, exist_ok=True)
    cleanup_stale_temps()
    print(f"鲸鲸文件箱 http://127.0.0.1:{PORT}  root={ROOT}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
