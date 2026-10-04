# -*- coding: utf-8 -*-
"""BookForge — 本地网页服务（零第三方依赖）。

启动：python server.py [port]
默认端口 8777，浏览器访问 http://127.0.0.1:8777

功能：
  - 文字书：章节文本 -> EPUB / AZW3
  - 漫画书：有序图片 -> EPUB / AZW3（Calibre 转换）
"""

import io
import json
import os
import re
import subprocess
import tempfile
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import epub_builder

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
OUTPUT_DIR = BASE_DIR / "output"
# 静态文件白名单（防路径穿越，仅放行前端资源）
STATIC_FILES = {"tree_ops.js": "application/javascript; charset=utf-8"}
CALIBRE_CANDIDATES = [
    r"C:\Program Files\Calibre2\ebook-convert.exe",
    r"C:\Program Files (x86)\Calibre2\ebook-convert.exe",
    str(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Calibre2" / "ebook-convert.exe"),
]

MAX_IMAGE_BYTES = 60 * 1024 * 1024   # 单张图片上限 60MB
MAX_IMAGES = 500                     # 漫画单本最多 500 页
MAX_NODES = 3000                     # 文字书目录条目（含中间层级）上限
MAX_PAGES = 2000                     # 有正文的页面上限
MAX_DEPTH = 8                        # 目录最大层级（卷/篇/章/节…）
MAX_BODY_CHARS = 2_000_000           # 单节正文上限 200 万字符
MAX_NOTE_CHARS = 50_000              # 单条注释上限 5 万字符
MAX_NAMES = 20                       # 著者/译者人数上限
MAX_NAME_CHARS = 100                 # 单个姓名长度上限

LANGUAGES = {"zh": "zh", "en": "en", "ja": "ja", "ko": "ko", "fr": "fr", "de": "de"}


def find_calibre():
    for cand in CALIBRE_CANDIDATES:
        if os.path.exists(cand):
            return cand
    return None


def convert_to_azw3(epub_path: Path, azw3_path: Path) -> tuple:
    """调用 Calibre 把 EPUB 转为 AZW3。返回 (ok, message)。"""
    calibre = find_calibre()
    if not calibre:
        return False, "未找到 Calibre（ebook-convert）。请安装 Calibre 后重试。"
    try:
        proc = subprocess.run(
            [calibre, str(epub_path), str(azw3_path)],
            capture_output=True, timeout=600,
        )
    except subprocess.TimeoutExpired:
        return False, "AZW3 转换超时（>10 分钟）。请减少图片数量后重试。"
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", "replace")[-800:]
        return False, "Calibre 转换失败：%s" % (err or "未知错误")
    return True, "ok"


def parse_multipart(content_type: str, body: bytes):
    """解析 multipart/form-data，返回 (fields: dict[str,str], files: list[dict])。

    手工按 boundary 分割，不依赖 email 解析器的消息头怪癖。
    """
    m = re.search(r'boundary="?([^";]+)"?', content_type or "")
    if not m:
        raise ValueError("请求缺少 multipart boundary")
    delim = b"--" + m.group(1).encode("utf-8", "replace")
    fields, files = {}, []
    for raw in body.split(delim)[1:]:
        if raw.startswith(b"--"):        # 结束标记 --boundary--
            break
        raw = raw.lstrip(b"\r\n")
        header_blob, _, payload = raw.partition(b"\r\n\r\n")
        cd = ""
        ctype = ""
        for line in header_blob.split(b"\r\n"):
            if b":" in line:
                k, v = line.split(b":", 1)
                k = k.decode("latin-1", "replace").strip().lower()
                v = v.decode("utf-8", "replace").strip()
                if k == "content-disposition":
                    cd = v
                elif k == "content-type":
                    ctype = v
        if payload.endswith(b"\r\n"):    # 去掉 boundary 前的换行
            payload = payload[:-2]
        name_m = re.search(r'name="([^"]*)"', cd)
        name = name_m.group(1) if name_m else ""
        fname_m = re.search(r'filename="([^"]*)"', cd)
        if fname_m:
            files.append({
                "field": name,
                "filename": fname_m.group(1),
                "data": payload,
                "content_type": ctype or "application/octet-stream",
            })
        elif name:
            fields[name] = payload.decode("utf-8", "replace")
    return fields, files


def build_output_name(title: str, fmt: str) -> str:
    base = epub_builder.sanitize_filename(title)
    name = base
    n = 1
    while (OUTPUT_DIR / ("%s.%s" % (name, fmt))).exists():
        n += 1
        name = "%s-%d" % (base, n)
    return name


# ---------------------------------------------------------------------------
# 请求处理器
# ---------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    server_version = "BookForge/1.0"

    # ---- 基础 ----
    def log_message(self, fmt, *args):
        print("[BookForge]", fmt % args)

    def _send_bytes(self, status, body: bytes, ctype="text/html; charset=utf-8",
                    headers=None):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, obj, status=200):
        self._send_bytes(status, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                         "application/json; charset=utf-8")

    # ---- 路由 ----
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path == "/api/diag":
            import inspect
            src = inspect.getsource(epub_builder.build_text_epub)
            self._send_json({
                "epub_builder_file": epub_builder.__file__,
                "server_file": __file__,
                "build_has_repair": "_repair_marks" in src,
            })
        elif path in ("/", "/index.html"):
            self._serve_index()
        elif path.startswith("/output/"):
            self._serve_output(path)
        elif path.lstrip("/") in STATIC_FILES:
            self._serve_static(path.lstrip("/"))
        else:
            self._send_bytes(404, b"Not Found", "text/plain; charset=utf-8")

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/build":
            self._handle_build()
        elif parsed.path == "/api/import-epub":
            self._handle_import_epub()
        elif parsed.path == "/api/import-docx":
            self._handle_import_docx()
        elif parsed.path == "/api/reset":
            self._handle_reset()
        else:
            self._send_json({"ok": False, "error": "未知接口"}, 404)

    def _handle_reset(self):
        """页面被关闭/刷新时调用：清空 output 产物缓存。"""
        try:
            if OUTPUT_DIR.exists():
                for f in OUTPUT_DIR.iterdir():
                    try:
                        if f.is_file():
                            f.unlink()
                        elif f.is_dir():
                            import shutil
                            shutil.rmtree(f, ignore_errors=True)
                    except OSError:
                        pass  # 个别文件被占用时跳过，不阻塞
            self._send_json({"ok": True})
        except Exception as e:
            self._send_json({"ok": False, "error": str(e)}, 500)

    # ---- GET 实现 ----
    NO_CACHE = {"Cache-Control": "no-store"}

    def _serve_static(self, name):
        f = STATIC_DIR / name
        if not f.exists():
            self._send_bytes(404, b"Not Found", "text/plain; charset=utf-8")
            return
        self._send_bytes(200, f.read_bytes(), STATIC_FILES[name], self.NO_CACHE)

    def _serve_index(self):
        index_path = STATIC_DIR / "index.html"
        if not index_path.exists():
            self._send_bytes(404, b"index.html not found", "text/plain")
            return
        self._send_bytes(200, index_path.read_bytes(), headers=self.NO_CACHE)

    def _serve_output(self, path):
        """只允许下载 output 目录内的文件，阻止路径穿越。"""
        rel = urllib.parse.unquote(path[len("/output/"):])
        rel = rel.split("?", 1)[0].split("#", 1)[0]
        if not rel or ".." in rel or "/" in rel or "\\" in rel:
            self._send_json({"ok": False, "error": "非法文件名"}, 400)
            return
        target = OUTPUT_DIR / rel
        if not target.exists() or not target.is_file():
            self._send_json({"ok": False, "error": "文件不存在或已清理"}, 404)
            return
        mime = {
            ".epub": "application/epub+zip",
            ".azw3": "application/x-mobipocket-ebook",
            ".mobi": "application/x-mobipocket-ebook",
        }.get(target.suffix.lower(), "application/octet-stream")
        # HTTP 头只允许 latin-1；中文文件名用 RFC 5987 filename* 编码
        ascii_name = target.name.encode("ascii", "replace").decode("ascii")
        quoted_name = urllib.parse.quote(target.name, safe="._-")
        disposition = (
            'attachment; filename="%s"; filename*=UTF-8\'\'%s'
            % (ascii_name, quoted_name)
        )
        self._send_bytes(200, target.read_bytes(), mime,
                         {"Content-Disposition": disposition})

    # ---- POST 实现 ----
    def _handle_import_epub(self):
        """解析上传的 EPUB：返回章节树与元数据，供前端回填表单。"""
        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            self._send_json({"ok": False, "error": "请求长度无效"}, 400)
            return
        if length <= 0 or length > 1_500_000_000:
            self._send_json({"ok": False, "error": "请求体为空或超出大小上限"}, 400)
            return
        try:
            body = self.rfile.read(length)
            fields, files = parse_multipart(self.headers.get("Content-Type", ""), body)
        except Exception as exc:
            self._send_json({"ok": False, "error": "请求解析失败：%s" % exc}, 400)
            return
        epub_file = next((f for f in files if f["field"] == "file"), None)
        if epub_file is None:
            self._send_json({"ok": False, "error": "请选择要导入的 EPUB 文件"}, 400)
            return
        if len(epub_file["data"]) > MAX_IMAGE_BYTES:
            self._send_json({"ok": False, "error": "EPUB 文件超过 60MB 上限"}, 400)
            return
        tmp_path = None
        try:
            fd, tmp_path = tempfile.mkstemp(prefix="bookforge_import_", suffix=".epub")
            with os.fdopen(fd, "wb") as fh:
                fh.write(epub_file["data"])
            meta = epub_builder.parse_epub(tmp_path)
            self._send_json({"ok": True, "meta": meta})
        except ValueError as exc:
            self._send_json({"ok": False, "error": str(exc)}, 400)
        except Exception as exc:
            import traceback
            traceback.print_exc()
            self._send_json({"ok": False, "error": "EPUB 解析失败：%s" % exc}, 500)
        finally:
            if tmp_path:
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

    def _handle_import_docx(self):
        """解析上传的 DOCX：返回章节树与元数据，供前端回填表单。"""
        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            self._send_json({"ok": False, "error": "请求长度无效"}, 400)
            return
        if length <= 0 or length > 1_500_000_000:
            self._send_json({"ok": False, "error": "请求体为空或超出大小上限"}, 400)
            return
        try:
            body = self.rfile.read(length)
            fields, files = parse_multipart(self.headers.get("Content-Type", ""), body)
        except Exception as exc:
            self._send_json({"ok": False, "error": "请求解析失败：%s" % exc}, 400)
            return
        docx_file = next((f for f in files if f["field"] == "file"), None)
        if docx_file is None:
            self._send_json({"ok": False, "error": "请选择要导入的 DOCX 文件"}, 400)
            return
        if len(docx_file["data"]) > MAX_IMAGE_BYTES:
            self._send_json({"ok": False, "error": "DOCX 文件超过 60MB 上限"}, 400)
            return
        tmp_path = None
        try:
            fd, tmp_path = tempfile.mkstemp(prefix="bookforge_import_", suffix=".docx")
            with os.fdopen(fd, "wb") as fh:
                fh.write(docx_file["data"])
            meta = epub_builder.parse_docx(tmp_path)
            self._send_json({"ok": True, "meta": meta})
        except ValueError as exc:
            self._send_json({"ok": False, "error": str(exc)}, 400)
        except Exception as exc:
            import traceback
            traceback.print_exc()
            self._send_json({"ok": False, "error": "DOCX 解析失败：%s" % exc}, 500)
        finally:
            if tmp_path:
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

    def _handle_build(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            self._send_json({"ok": False, "error": "请求长度无效"}, 400)
            return
        if length <= 0 or length > 1_500_000_000:  # 1.5GB 上限
            self._send_json({"ok": False, "error": "请求体为空或超出大小上限"}, 400)
            return
        try:
            body = self.rfile.read(length)
            fields, files = parse_multipart(self.headers.get("Content-Type", ""), body)
        except Exception as exc:
            self._send_json({"ok": False, "error": "请求解析失败：%s" % exc}, 400)
            return

        btype = fields.get("type", "").strip()
        title = fields.get("title", "").strip() or "未命名书籍"
        authors = Handler._parse_names(fields.get("authors")) or ["未知作者"]
        translators = Handler._parse_names(fields.get("translators"))
        publisher = (fields.get("publisher") or "").strip()[:200] or None
        pub_date = Handler._normalize_pub_date(
            fields.get("pub_date") or fields.get("pub_year") or "")
        isbn = (fields.get("isbn") or "").strip()[:40] or None
        indent_2em = fields.get("indent_2em") != "0"   # 默认开启首行缩进
        split_mode = "line" if fields.get("split_mode") != "blank" else "blank"
        notes_mode = "endbook" if fields.get("notes_mode") == "endbook" else "chapter"
        language = fields.get("language", "").strip() or "zh"
        language = LANGUAGES.get(language, "zh")
        want_epub = fields.get("epub") == "1"
        want_azw3 = fields.get("azw3") == "1"
        if not want_epub and not want_azw3:
            want_epub = True  # 默认至少产出 EPUB

        try:
            if btype == "text":
                result = self._build_text_book(fields, files, title, authors,
                                               translators, language,
                                               publisher, pub_date, isbn,
                                               indent_2em, split_mode, notes_mode,
                                               want_epub, want_azw3)
            elif btype == "comic":
                result = self._build_comic_book(files, title, authors,
                                                translators, language,
                                                publisher, pub_date, isbn,
                                                want_epub, want_azw3)
            else:
                self._send_json({"ok": False, "error": "未知书籍类型"}, 400)
                return
            self._send_json(result)
        except ValueError as exc:
            self._send_json({"ok": False, "error": str(exc)}, 400)
        except Exception as exc:
            import traceback
            traceback.print_exc()
            self._send_json({"ok": False, "error": "生成失败：%s" % exc}, 500)

    # ---- 构建逻辑 ----
    @staticmethod
    def _validate_tree(nodes, depth=1, stats=None):
        """递归校验树形章节，返回归一化树（只保留有标题/正文/子节点的条目）。"""
        if not isinstance(nodes, list):
            raise ValueError("章节数据格式错误")
        if depth > MAX_DEPTH:
            raise ValueError("目录层级超过上限（%d 层）" % MAX_DEPTH)
        if stats is None:
            stats = {"nodes": 0, "pages": 0}
        result = []
        for item in nodes:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()
            content = str(item.get("content") or "").strip()
            children_raw = item.get("children") or []
            if not isinstance(children_raw, list):
                raise ValueError("章节数据格式错误")
            if len(content) > MAX_BODY_CHARS:
                raise ValueError("单节正文超过 200 万字符上限")
            # 注释表校验：{编号: 文本}
            notes_raw = item.get("notes")
            notes = {}
            if notes_raw:
                if not isinstance(notes_raw, dict):
                    raise ValueError("注释数据格式错误")
                for k, v in notes_raw.items():
                    if not re.fullmatch(r"\d{1,4}", str(k)):
                        raise ValueError("注释编号格式错误：%s" % k)
                    text = str(v)
                    if len(text) > MAX_NOTE_CHARS:
                        raise ValueError("单条注释超过 %d 字符上限" % MAX_NOTE_CHARS)
                    notes[str(k)] = text
            stats["nodes"] += 1
            if stats["nodes"] > MAX_NODES:
                raise ValueError("目录条目总数超过上限（%d 条）" % MAX_NODES)
            if content:
                stats["pages"] += 1
                if stats["pages"] > MAX_PAGES:
                    raise ValueError("有正文的页面超过上限（%d 页）" % MAX_PAGES)
            children = Handler._validate_tree(children_raw, depth + 1, stats)
            # 保留注释区标记与标题角标（前端树传输时不得丢失，否则篇级注释池失效）
            tm_raw = item.get("title_marks")
            title_marks = []
            if isinstance(tm_raw, list):
                for x in tm_raw:
                    if re.fullmatch(r"\d{1,4}", str(x)):
                        title_marks.append(str(x))
            plain = bool(item.get("_plain_notes"))
            if title or content or children or notes:
                result.append({"title": title, "content": content,
                               "notes": notes, "title_marks": title_marks,
                               "_plain_notes": plain, "children": children})
        return result

    @staticmethod
    def _parse_names(raw):
        """解析著者/译者字段：JSON 数组；容错逗号/顿号分隔字符串。"""
        if not raw:
            return []
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                names = [str(x).strip() for x in data if str(x).strip()]
            elif isinstance(data, str):
                names = [x.strip() for x in re.split(r"[，,、;；]", data) if x.strip()]
            else:
                names = []
        except json.JSONDecodeError:
            names = [x.strip() for x in re.split(r"[，,、;；]", raw) if x.strip()]
        if len(names) > MAX_NAMES:
            raise ValueError("著者/译者人数超过上限（%d 人）" % MAX_NAMES)
        for n in names:
            if len(n) > MAX_NAME_CHARS:
                raise ValueError("姓名长度超过上限（%d 字符）" % MAX_NAME_CHARS)
        return names

    @staticmethod
    def _normalize_pub_date(raw):
        """归一化出版时间：空 -> None；"2026" -> 年份；"2026-1-3" -> "2026-01-03"；非法 -> None。"""
        if not raw:
            return None
        v = str(raw).strip()
        m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})$", v)
        if m:
            return "%s-%s-%s" % (m.group(1), m.group(2).zfill(2), m.group(3).zfill(2))
        if re.match(r"^\d{4}$", v):
            return v
        return None

    @staticmethod
    def _iter_nodes(nodes):
        """深度优先遍历树节点（供统计使用）。"""
        for n in nodes:
            yield n
            yield from Handler._iter_nodes(n.get("children") or [])

    def _build_text_book(self, fields, files, title, authors, translators, language,
                         publisher, pub_date, isbn, indent_2em, split_mode,
                         notes_mode, want_epub, want_azw3):
        try:
            chapters_raw = json.loads(fields.get("chapters", "[]"))
        except json.JSONDecodeError:
            raise ValueError("章节数据格式错误")
        chapters = self._validate_tree(chapters_raw)
        if not chapters or not any(
                (n.get("content") or "").strip()
                for n in self._iter_nodes(chapters)):
            raise ValueError("请至少添加一个有正文的章节")

        # 封面（可选）
        cover_path = None
        cover_file = next((f for f in files if f["field"] == "cover"), None)
        if cover_file:
            cover_path = self._save_upload(cover_file, "cover")
            try:
                epub_builder.image_mime(Path(cover_path))
            except ValueError as exc:
                raise ValueError("封面上传失败：%s" % exc)

        base = build_output_name(title, "epub")
        outputs = []
        epub_path = None
        if want_epub:
            epub_path = OUTPUT_DIR / ("%s.epub" % base)
            epub_builder.build_text_epub(epub_path, title, authors, translators,
                                         language, chapters, cover_path=cover_path,
                                         publisher=publisher, pub_date=pub_date,
                                         isbn=isbn, indent_2em=indent_2em,
                                         split_mode=split_mode, notes_mode=notes_mode)
            outputs.append(self._describe(epub_path))
        if want_azw3:
            if epub_path is None:
                epub_path = OUTPUT_DIR / ("%s.epub" % base)
                epub_builder.build_text_epub(epub_path, title, authors, translators,
                                             language, chapters, cover_path=cover_path,
                                             publisher=publisher, pub_date=pub_date,
                                             isbn=isbn, indent_2em=indent_2em,
                                             split_mode=split_mode, notes_mode=notes_mode)
            azw3_path = OUTPUT_DIR / ("%s.azw3" % base)
            ok, msg = convert_to_azw3(epub_path, azw3_path)
            if ok:
                outputs.append(self._describe(azw3_path))
            else:
                self._cleanup_temp(cover_path)
                raise ValueError(msg)
        self._cleanup_temp(cover_path)
        return {"ok": True, "files": outputs, "title": title}

    def _build_comic_book(self, files, title, authors, translators, language,
                          publisher, pub_date, isbn, want_epub, want_azw3):
        images = [f for f in files if f["field"] == "images"]
        if not images:
            raise ValueError("请至少上传一张图片")
        if len(images) > MAX_IMAGES:
            raise ValueError("图片数量超过上限（%d 张）" % MAX_IMAGES)
        # 前端已按顺序提交；这里校验大小并落盘
        tmp_dir = Path(tempfile.mkdtemp(prefix="bookforge_comic_"))
        try:
            paths = []
            for i, img in enumerate(images, start=1):
                if len(img["data"]) > MAX_IMAGE_BYTES:
                    raise ValueError("第 %d 张图片超过 60MB 上限" % i)
                ext = Path(img["filename"]).suffix.lower() or ".jpg"
                p = tmp_dir / ("page_%03d%s" % (i, ext))
                p.write_bytes(img["data"])
                epub_builder.image_mime(p)  # 校验格式
                paths.append(p)
            base = build_output_name(title, "epub")
            outputs = []
            epub_path = None
            if want_epub:
                epub_path = OUTPUT_DIR / ("%s.epub" % base)
                epub_builder.build_comic_epub(epub_path, title, authors,
                                              translators, language, paths,
                                              cover_use_first=True,
                                              publisher=publisher, pub_date=pub_date,
                                              isbn=isbn)
                outputs.append(self._describe(epub_path))
            if want_azw3:
                if epub_path is None:
                    epub_path = OUTPUT_DIR / ("%s.epub" % base)
                    epub_builder.build_comic_epub(epub_path, title, authors,
                                                  translators, language, paths,
                                                  cover_use_first=True,
                                                  publisher=publisher,
                                                  pub_date=pub_date, isbn=isbn)
                azw3_path = OUTPUT_DIR / ("%s.azw3" % base)
                ok, msg = convert_to_azw3(epub_path, azw3_path)
                if ok:
                    outputs.append(self._describe(azw3_path))
                else:
                    raise ValueError(msg)
            return {"ok": True, "files": outputs, "title": title}
        finally:
            import shutil
            shutil.rmtree(tmp_dir, ignore_errors=True)

    # ---- 辅助 ----
    @staticmethod
    def _save_upload(file_info, prefix) -> str:
        data = file_info["data"]
        if len(data) > MAX_IMAGE_BYTES:
            raise ValueError("上传文件超过 60MB 上限")
        ext = Path(file_info["filename"]).suffix.lower() or ".jpg"
        tmp = Path(tempfile.mkdtemp(prefix="bookforge_upload_"))
        p = tmp / ("%s%s" % (prefix, ext))
        p.write_bytes(data)
        return str(p)

    @staticmethod
    def _cleanup_temp(path):
        if path:
            try:
                Path(path).parent  # 仅清理我们创建的临时目录
                import shutil
                shutil.rmtree(Path(path).parent, ignore_errors=True)
            except Exception:
                pass

    @staticmethod
    def _describe(path: Path) -> dict:
        return {
            "name": path.name,
            "url": "/output/" + urllib.parse.quote(path.name),
            "size": path.stat().st_size,
            "fmt": path.suffix.lstrip(".").upper(),
        }


def main():
    port = 8777
    import sys
    if len(sys.argv) > 1:
        port = int(sys.argv[1])
    calibre = find_calibre()
    print("=" * 52)
    print("  BookForge — Self-Hosted Kindle E-book Maker")
    print("  URL: http://127.0.0.1:%d" % port)
    print("  Calibre : %s" % (calibre or "not found (AZW3 conversion unavailable)"))
    print("  Press Ctrl+C to stop")
    print("=" * 52)
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nBookForge stopped.")
        server.server_close()


if __name__ == "__main__":
    main()
