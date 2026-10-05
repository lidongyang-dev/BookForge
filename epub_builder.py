# -*- coding: utf-8 -*-
"""BookForge — EPUB 书籍生成核心（文字书 / 漫画书）。

基于标准库 zipfile 手工构建 EPUB 3 文件结构，
并附带 EPUB 2 风格 NCX 导航，以兼容旧款 Kindle 设备。

结构（EPUB 本质是一个特定布局的 ZIP）：
    mimetype                     -> "application/epub+zip"（必须首个写入且不压缩）
    META-INF/container.xml       -> 指向 OEBPS/content.opf
    OEBPS/content.opf            -> 包描述（元数据 / manifest / spine）
    OEBPS/nav.xhtml              -> EPUB3 导航文档
    OEBPS/toc.ncx                -> EPUB2 NCX（兼容层）
    OEBPS/chapter_XXX.xhtml      -> 章节 / 漫画页
    OEBPS/images/...             -> 图片资源
"""

import html
import re
import uuid
import zipfile
import datetime
import xml.etree.ElementTree as ET
from pathlib import Path

# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------

def sanitize_filename(name: str, fallback: str = "book") -> str:
    """清理文件名中的非法字符，防止路径穿越与非法文件名。"""
    cleaned = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", str(name))
    cleaned = cleaned.strip().strip(".")
    return cleaned or fallback


def escape_text(text: str) -> str:
    """转义用户输入（标题 / 正文 / 作者），防止注入非预期 HTML。"""
    return html.escape(str(text), quote=True)


def paragraphs_from_text(text: str, split_mode: str = "blank"):
    """纯文本 -> 段落列表。

    split_mode="blank"（默认，适合英文）: 空行分段，段内单换行合并为空格。
    split_mode="line"（适合中文）: 每个回车即新段落，逐行切分。
    """
    text = str(text).replace("\r\n", "\n").replace("\r", "\n")
    if split_mode == "line":
        paras = []
        for ln in text.split("\n"):
            t = re.sub(r"\s+", " ", ln).strip()
            if t:
                paras.append(t)
        return paras
    blocks = re.split(r"\n[ \t]*\n", text.strip())
    paragraphs = []
    for block in blocks:
        lines = [re.sub(r"\s+", " ", ln).strip() for ln in block.split("\n")]
        joined = " ".join(ln for ln in lines if ln)
        if joined:
            paragraphs.append(joined)
    return paragraphs


_IMAGE_EXT_MIME = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
}


def image_mime(path: Path) -> str:
    """根据扩展名返回 Kindle 可用的图片 MIME；不支持则抛 ValueError。"""
    ext = path.suffix.lower()
    mime = _IMAGE_EXT_MIME.get(ext)
    if not mime:
        raise ValueError(
            f"不支持的图片格式：{ext or '(无扩展名)'}。"
            "Kindle 支持 JPG / PNG / GIF，请先转换后再上传。"
        )
    return mime


def _now_iso() -> str:
    """EPUB 规范要求的 dcterms:modified 时间戳（UTC, W3CDTF）。"""
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _xhtml_document(title: str, body_html: str, extra_head: str = "") -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE html>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml" '
        'xmlns:epub="http://www.idpf.org/2007/ops">\n'
        "<head>\n<meta charset=\"utf-8\"/>\n<title>{title}</title>{extra_head}\n</head>\n"
        "<body>\n{body}\n</body>\n</html>"
    ).format(title=escape_text(title), extra_head=extra_head, body=body_html)


# ---------------------------------------------------------------------------
# EPUB 组装
# ---------------------------------------------------------------------------

class _TocNode:
    """目录树节点。href 为空表示纯分类节点（卷/篇等中间层级）。"""

    def __init__(self, label: str, href=None, children=None):
        self.label = label
        self.href = href
        self.children = children or []


class _EpubWriter:
    """逐步写入一个 EPUB 文件。"""

    def __init__(self, out_path: Path, uid: str):
        self.out_path = out_path
        self.uid = uid
        self.manifest = []   # (id, href, media_type, properties)
        self.spine = []      # (idref, properties)
        self.toc_tree = []   # list[_TocNode]

    def open(self) -> zipfile.ZipFile:
        zf = zipfile.ZipFile(self.out_path, "w", zipfile.ZIP_DEFLATED)
        # mimetype 必须第一个写入、且不压缩
        zf.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        return zf

    def add_container(self, zf: zipfile.ZipFile):
        container = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<container version="1.0" '
            'xmlns="urn:oasis:names:tc:opendocument:xmlns:container">\n'
            '  <rootfiles>\n'
            '    <rootfile full-path="OEBPS/content.opf" '
            'media-type="application/oebps-package+xml"/>\n'
            '  </rootfiles>\n'
            "</container>\n"
        )
        zf.writestr("META-INF/container.xml", container.encode("utf-8"))

    def add_manifest_item(self, item_id, href, media_type, properties=""):
        self.manifest.append((item_id, href, media_type, properties))

    def add_spine_item(self, idref, properties=""):
        self.spine.append((idref, properties))

    def add_toc_node(self, node: _TocNode):
        self.toc_tree.append(node)

    def write_content_opf(self, zf, title, authors, translators, language,
                          cover_item_id=None, fixed_layout=False,
                          publisher=None, pub_date=None, isbn=None):
        meta_extra = ""
        if cover_item_id:
            meta_extra += '<meta name="cover" content="%s"/>' % cover_item_id
        if fixed_layout:
            meta_extra += (
                '<meta property="rendition:layout">pre-paginated</meta>'
                '<meta property="rendition:orientation">auto</meta>'
            )

        meta_meta = ""
        if publisher:
            meta_meta += '    <dc:publisher>%s</dc:publisher>\n' % escape_text(publisher)
        if pub_date:
            if re.match(r"^\d{4}-\d{2}-\d{2}$", pub_date):
                meta_meta += ('    <dc:date opf:event="publication">%s</dc:date>\n'
                              % escape_text(pub_date))
            else:
                meta_meta += '    <dc:date>%s</dc:date>\n' % escape_text(pub_date)
        if isbn:
            meta_meta += '    <dc:identifier opf:scheme="ISBN">%s</dc:identifier>\n' % escape_text(isbn)

        # 著者(aut)与译者(trl)均可多人，按角色输出多个 dc:creator
        creators_xml = ""
        for a in authors:
            creators_xml += '    <dc:creator opf:role="aut">%s</dc:creator>\n' % escape_text(a)
        for t in translators:
            creators_xml += '    <dc:creator opf:role="trl">%s</dc:creator>\n' % escape_text(t)
        if not creators_xml:
            creators_xml = '    <dc:creator opf:role="aut">未知作者</dc:creator>\n'

        manifest_xml = "".join(
            '    <item id="{id}" href="{href}" media-type="{mt}"{props}/>\n'.format(
                id=iid, href=href, mt=mt,
                props=(' properties="%s"' % p) if p else "",
            )
            for iid, href, mt, p in self.manifest
        )
        spine_xml = "".join(
            '    <itemref idref="{idref}"{props}/>\n'.format(
                idref=idref, props=(' properties="%s"' % p) if p else "",
            )
            for idref, p in self.spine
        )

        opf = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<package xmlns="http://www.idpf.org/2007/opf" '
            'xmlns:opf="http://www.idpf.org/2007/opf" version="3.0" '
            'unique-identifier="uid">\n'
            '  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
            '    <dc:identifier id="uid">{uid}</dc:identifier>\n'
            '    <dc:title>{title}</dc:title>\n'
            '{creators}'
            '    <dc:language>{lang}</dc:language>\n'
            '{meta_meta}'
            '    <meta property="dcterms:modified">{modified}</meta>\n'
            '{meta_extra}'
            '  </metadata>\n'
            '  <manifest>\n'
            '{manifest}'
            '  </manifest>\n'
            '  <spine>\n'
            '{spine}'
            '  </spine>\n'
            '</package>\n'
        ).format(
            uid=escape_text(self.uid),
            title=escape_text(title),
            creators=creators_xml,
            lang=escape_text(language),
            meta_meta=meta_meta,
            modified=_now_iso(),
            meta_extra=meta_extra,
            manifest=manifest_xml,
            spine=spine_xml,
        )
        zf.writestr("OEBPS/content.opf", opf.encode("utf-8"))

    def write_nav(self, zf, title):
        """EPUB3 导航：递归渲染多级目录。"""
        def render(nodes):
            items = []
            for n in nodes:
                if n.href:
                    a = '<a href="%s">%s</a>' % (n.href, escape_text(n.label))
                else:
                    a = "<span>%s</span>" % escape_text(n.label)
                inner = render(n.children) if n.children else ""
                items.append("<li>%s%s</li>" % (a, inner))
            return "<ol>\n%s</ol>\n" % "".join(items)

        nav = _xhtml_document(
            "目录",
            '<nav epub:type="toc" xmlns:epub="http://www.idpf.org/2007/ops">'
            "<h1>{}</h1>\n{}</nav>".format(escape_text(title), render(self.toc_tree)),
        )
        zf.writestr("OEBPS/nav.xhtml", nav.encode("utf-8"))
        # EPUB3 规范要求 nav 出现在 manifest 且 properties="nav"（先注册，
        # content.opf 后写，manifest 列表会包含它）
        self.add_manifest_item("nav", "nav.xhtml", "application/xhtml+xml", "nav")

    def write_ncx(self, zf, title):
        """EPUB2 NCX：递归生成多级 navPoint。"""
        counter = [0]

        def render(nodes):
            out = []
            for n in nodes:
                counter[0] += 1
                i = counter[0]
                out.append('    <navPoint id="navpoint-%d" playOrder="%d">' % (i, i))
                out.append('      <navLabel><text>%s</text></navLabel>'
                           % escape_text(n.label))
                if n.href:
                    out.append('      <content src="%s"/>' % n.href)
                if n.children:
                    out.append("      <navMap>")
                    out.append(render(n.children))
                    out.append("      </navMap>")
                out.append("    </navPoint>")
            return "\n".join(out)

        points = render(self.toc_tree)
        ncx = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">\n'
            '  <head>\n'
            '    <meta name="dtb:uid" content="{uid}"/>\n'
            '    <meta name="dtb:depth" content="{depth}"/>\n'
            '    <meta name="dtb:totalPageCount" content="0"/>\n'
            '    <meta name="dtb:maxPageNumber" content="0"/>\n'
            '  </head>\n'
            '  <docTitle><text>{title}</text></docTitle>\n'
            '  <navMap>\n'
            '{points}'
            '  </navMap>\n'
            '</ncx>\n'
        ).format(uid=escape_text(self.uid), title=escape_text(title),
                 depth=min(max(counter[0], 1), 9999), points=points)
        zf.writestr("OEBPS/toc.ncx", ncx.encode("utf-8"))
        self.add_manifest_item("ncx", "toc.ncx", "application/x-dtbncx+xml")

    def close(self, zf):
        zf.close()


def _make_uid(title: str) -> str:
    return "bookforge-%s" % uuid.uuid5(uuid.NAMESPACE_URL, title + str(uuid.uuid4())).hex[:16]


# ---------------------------------------------------------------------------
# 对外 API：文字书
# ---------------------------------------------------------------------------

_NOTE_RE = re.compile(r"〔(\d+)〕")


def _linkify_paragraph(text: str, notes: dict, chapter_no: int, gmap=None,
                       href_idx=None):
    """把段落纯文本转成 HTML；已配对的〔N〕注释标记变为注释链接，其余转义。

    gmap：书末注（endbook）模式的 {本地注释号: 全局注释号} 映射，链接指向
    书末统一注释章节（#note-g{N}）；为 None 时按章末脚注模式生成
    （href="#note-章号-编号"）。href_idx：章末脚注模式下锚点所在页（篇末
    渲染页）；为 None 时用本页。返回 (html, 本段引用的注释编号列表[去重保序])。
    """
    parts = _NOTE_RE.split(text)
    html_parts = []
    refs = []
    for i, part in enumerate(parts):
        if i % 2 == 0:
            html_parts.append(escape_text(part))
            continue
        no = part
        if gmap is not None:
            g = gmap.get(no)
            if g and str(notes.get(no, "")).strip():
                if not isinstance(g, int):
                    # 共享注释池（章末脚注模式）：本地原号，跨文件指向本篇末渲染页
                    if no not in refs:
                        refs.append(no)
                    target = href_idx or chapter_no
                    html_parts.append(
                        '<a epub:type="noteref" id="noteref-%d-%s" '
                        'href="chapter_%03d.xhtml#note-%d-%s">'
                        "<sup>〔%s〕</sup></a>"
                        % (chapter_no, no, target, target, no, no)
                    )
                else:
                    # 书末注（endbook）模式：全局号，指向书末统一注释章节
                    html_parts.append(
                        '<a epub:type="noteref" id="noteref-g%s" href="#note-g%s">'
                        "<sup>〔%s〕</sup></a>" % (g, g, g)
                    )
            else:
                html_parts.append("〔%s〕" % escape_text(no))
        elif no in notes and str(notes.get(no, "")).strip():
            if no not in refs:
                refs.append(no)
            html_parts.append(
                '<a epub:type="noteref" id="noteref-%d-%s" '
                'href="chapter_%03d.xhtml#note-%d-%s">'
                "<sup>〔%s〕</sup></a>"
                % (chapter_no, no, chapter_no, chapter_no, no, no)
            )
        else:
            html_parts.append("〔%s〕" % escape_text(no))
    return "".join(html_parts), refs


def _chapter_notes_html(refs, notes: dict, chapter_no: int,
                        back_pages=None) -> str:
    """生成章末注释区（EPUB 标准 footnotes）。back_pages: {注释号: 首个引用页}，
    返回链接指向该页的角标；缺省回退到注释区所在页。"""
    items = []
    for no in refs:
        text = escape_text(str(notes.get(no, "")))
        back = (back_pages or {}).get(no, chapter_no)
        items.append(
            '<aside epub:type="footnote" id="note-%d-%s">'
            "<p>〔%s〕%s</p>"
            '<p><a href="chapter_%03d.xhtml#noteref-%d-%s">↑ 返回正文</a></p>'
            "</aside>" % (chapter_no, no, no, text, back, back, no)
        )
    return ('<section epub:type="footnotes"><h2>注释</h2>%s</section>'
            % "".join(items))


def _normalize_chapters(chapters):
    """把章节数据归一化为树形结构 dict 列表。

    兼容两种输入：
      旧格式 [("标题", "正文"), ...]
      新格式 [{"title":..., "content":..., "notes": {...}, "children":[...]}, ...]
    返回 list[dict]，节点键：title / content / notes / children。
    """
    if isinstance(chapters, (list, tuple)):
        # 检测旧格式：元素是 2 元组
        if chapters and all(isinstance(c, (tuple, list)) and len(c) == 2 for c in chapters):
            return [{"title": c[0], "content": c[1], "children": [],
                     "notes": {}} for c in chapters]
    nodes = []
    for item in chapters:
        if not isinstance(item, dict):
            continue
        notes = item.get("notes")
        if not isinstance(notes, dict):
            notes = {}
        nodes.append({
            "title": str(item.get("title") or ""),
            "content": str(item.get("content") or ""),
            "notes": {str(k): str(v) for k, v in notes.items()},
            "children": _normalize_chapters(item.get("children") or []),
            # 保留注释感知附加字段（标题行标记 / 纯文本注释区标记）
            "title_marks": [str(m) for m in (item.get("title_marks") or [])],
            "_plain_notes": bool(item.get("_plain_notes")),
        })
    return nodes


def _names(value):
    """把著者/译者参数归一化为字符串列表（兼容传入单个字符串或列表）。"""
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, (list, tuple)):
        return [str(v).strip() for v in value if str(v).strip()]
    return []


def _fmt_pub_date(d):
    """出版时间展示：2026-10-03 -> 2026年10月3日；2026 -> 2026。"""
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})$", d or "")
    if m:
        return "%s年%s月%s日" % (m.group(1), int(m.group(2)), int(m.group(3)))
    return d or ""


def _copyright_xhtml(title, authors, translators, publisher, pub_date, isbn):
    """版权页 HTML 主体：书名 + 著/译 + 出版社/出版时间/ISBN + 版权声明。"""
    lines = ['<div class="copyright" style="line-height:2.0">']
    lines.append('<h1 style="font-size:1.4em">%s</h1>' % escape_text(title))
    if authors:
        lines.append('<p>著　%s</p>' % escape_text("、".join(authors)))
    if translators:
        lines.append('<p>译　%s</p>' % escape_text("、".join(translators)))
    if publisher:
        lines.append('<p>出版社：%s</p>' % escape_text(publisher))
    if pub_date:
        lines.append('<p>出版时间：%s</p>' % escape_text(_fmt_pub_date(pub_date)))
    if isbn:
        lines.append('<p>ISBN：%s</p>' % escape_text(isbn))
    who = "、".join(authors) if authors else "本书作者"
    year = pub_date[:4] if pub_date else ""
    notice = "© %s %s。保留所有权利。" % (year or "（未标注年份）", who)
    lines.append('<p style="font-size:0.85em;color:#666;margin-top:1.6em">%s</p>'
                 % escape_text(notice))
    lines.append('<p style="font-size:0.85em;color:#666">本书由 BookForge 制作。</p>')
    lines.append("</div>")
    return "\n".join(lines)


def build_text_epub(out_path, title, authors, translators, language, chapters,
                    cover_path=None, uid=None, fixed_layout=False,
                    publisher=None, pub_date=None, isbn=None,
                    indent_2em=True, split_mode="line", notes_mode="chapter"):
    """生成文字书 EPUB（支持多级目录：卷 → 篇 → 章 → 节）。

    authors / translators: 著者与译者，可传字符串（单人）或字符串列表（多人）。
    chapters: 树形章节结构，例如：
        [
          {"title": "第一卷", "content": "", "children": [
              {"title": "第一篇", "content": "篇首引言……", "children": [
                  {"title": "第一章", "content": "正文……", "children": []},
              ]},
          ]},
        ]
      - content 非空（有正文）的节点 -> 生成独立页面（正文自动分段）。
      - content 为空（纯分类）的节点 -> 只出现在目录中，可点击跳到其首个后代页面。
      - 也兼容旧扁平格式 [("标题", "正文"), ...]。
    cover_path: 可选封面图片路径（JPG/PNG/GIF）。
    publisher / pub_date / isbn: 可选版权信息，写入 OPF 元数据并展示在版权页。
    pub_date 支持 "2026"（仅年份）或 "2026-10-03"（精确到日），可留空。
    indent_2em: 段落首行缩进 2 字符（中文排版习惯，默认开）。
    split_mode: 段落切分方式——"line"每个回车即新段（中文习惯，默认）；
                "blank"空行分段、段内换行合并为空格（英文习惯）。
    notes_mode: 注释形式——"chapter"章末脚注（每章末尾注释区，默认）；
                "endbook"书末注释（全书注释统一编号，正文链接指向书末"注释"章节）。
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    uid = uid or _make_uid(title)
    w = _EpubWriter(out_path, uid)
    chapters = _normalize_chapters(chapters)

    # —— 注释感知字段兜底 ——
    # 树形数据经前端传输/旧数据可能丢失 _plain_notes（注释区标记）与
    # title_marks（标题行角标）：凡能由 content/title 重算的（粘贴文本、
    # 标题带〔N〕）在此补算；content 已剥离注释区的场景依赖前端 cleanNode
    # 与服务端 _validate_tree 保留字段。
    def _repair_marks(nodes):
        for n in nodes:
            if n.get("notes"):
                if not n.get("_plain_notes"):
                    _body, _notes, _problems, _nc = _extract_plain_notes(
                        n.get("content", ""))
                    if _notes:
                        n["content"] = _body
                        n["notes"] = _notes
                        n["_plain_notes"] = True
                if not n.get("title_marks"):
                    _t = n.get("title") or ""
                    _marks = []
                    for _m in re.finditer(r"[〔\[](\d{1,4})[〕\]]", _t):
                        _marks.append(_m.group(1))
                    for _m in re.finditer(r"[①-⑳]", _t):
                        _marks.append(str(_CIRCLED_MAP[_m.group(0)]))
                    if _marks:
                        n["title_marks"] = _marks
                        n["title"] = re.sub(r"[〔\[]\d{1,4}[〕\]]", "", _t)
                        n["title"] = (re.sub(r"[①-⑳]", "", n["title"]).strip()
                                      or "（无标题）")
            _repair_marks(n.get("children") or [])
    _repair_marks(chapters)
    authors = _names(authors)
    translators = _names(translators)

    # 版权页（置于封面之后、正文之前）
    w.add_manifest_item("copyright", "copyright.xhtml", "application/xhtml+xml")
    w.add_spine_item("copyright")
    w.add_toc_node(_TocNode("版权页", "copyright.xhtml"))

    # 首行缩进：章节页 <head> 注入样式（版权页不缩进）
    extra_head = ""
    if indent_2em:
        extra_head = "<style>p{text-indent:2em;margin:0.5em 0;}</style>"

    # 封面（可选）
    cover_item_id = None
    if cover_path:
        cover_path = Path(cover_path)
        mime = image_mime(cover_path)
        ext = cover_path.suffix.lower()
        cover_item_id = "cover-image"
        w.add_manifest_item(cover_item_id, "images/cover" + ext, mime, "cover-image")

    # 先序遍历：注册页面 + 构建目录树
    pages = []   # (序号, href, body_html)
    page_no = [0]
    # 书末注（endbook）模式：全书统一注释
    endbook_mode = notes_mode == "endbook"
    next_global = [1]
    endbook_items = []   # [(全局注释号, 注释文本)]

    # 篇级注释池（书末注模式）：
    # 1) 注释区节点（_plain_notes）的直接父若满足"子节点中注释区唯一 + 有兄弟引用其
    #    注释号"，则注释表挂该父（覆盖篇内各节的跨节点配对）；
    # 2) 若该池被"挂载点子树之外"的节点引用（如注释集中在某章、标记散布整篇），
    #    则沿祖先上溯，直到遇到"另有其他来源注释池"的层级为止。
    # 各篇注释号独立（都从〔1〕起）时天然隔离，不串号；注释区自身由本节点
    # notes 配对，不依赖池。
    def _promote_notes_pools(chapters):
        parents = {}
        def bp(nodes, parent):
            for n in nodes:
                parents[id(n)] = parent
                bp(n.get("children") or [], n)
        bp(chapters, None)
        plain_nodes = []
        def scan(nodes):
            for n in nodes:
                if n.get("_plain_notes") and n.get("notes"):
                    plain_nodes.append(n)
                scan(n.get("children") or [])
        scan(chapters)
        plain_ids = {id(n) for n in plain_nodes}
        refs = []   # [(引用节点, 注释号)]
        def sr(nodes):
            for n in nodes:
                for m in re.finditer(r"[〔\[](\d{1,4})[〕\]]",
                                     n.get("content", "")):
                    refs.append((n, m.group(1)))
                for x in (n.get("title_marks") or []):
                    refs.append((n, str(x)))
                sr(n.get("children") or [])
        sr(chapters)
        # 每个引用的"本地注释区"：注释区自身→自身；否则归属 LCA 最深者
        def depth(n):
            d = 0
            while n is not None:
                d += 1
                n = parents.get(id(n))
            return d
        def lca(a, b):
            da, db = depth(a), depth(b)
            while da > db:
                a = parents.get(id(a)); da -= 1
            while db > da:
                b = parents.get(id(b)); db -= 1
            while a is not b:
                a = parents.get(id(a)); b = parents.get(id(b))
            return a
        local_of = {}   # id(引用节点) -> 注释区节点
        for rn, _ in refs:
            if id(rn) in plain_ids or rn.get("notes"):
                # 注释区自身 / 自带注释表（如 Word 原生脚注）的节点：自身即注释区
                local_of[id(rn)] = rn
                continue
            best, best_d, best_k = None, -1, None
            for k in plain_nodes:
                if not k.get("notes"):
                    continue
                l = lca(rn, k)
                d = depth(l)
                if d > best_d:
                    best_d, best, best_k = d, l, k
            if best is not None:
                local_of[id(rn)] = best_k
        def subtree(n):
            out = []
            def s(nodes):
                for x in nodes:
                    out.append(x)
                    s(x.get("children") or [])
            s(n.get("children") or [])
            return out
        # 1) 直接父挂池（记录注释区来源）
        def build(nodes):
            for n in nodes:
                kids = n.get("children") or []
                pk = [k for k in kids if id(k) in plain_ids]
                if len(pk) == 1:
                    k = pk[0]
                    keys = set(k["notes"])
                    # 兄弟引用者（正文/标题行角标）的号必须全部落在本注释区内，
                    # 才认为该注释区服务于"本父节点的整篇"——避免把兄弟篇的
                    # 同号引用误当成本篇引用（如中国社会各阶级的分析的注释
                    # 1~17 与湖南篇正文 1~27 撞号）
                    sib_nos = set()
                    for sib in kids:
                        if sib is k:
                            continue
                        for m in re.finditer(r"[〔\[](\d{1,4})[〕\]]",
                                             sib.get("content", "")):
                            sib_nos.add(m.group(1))
                        for x in (sib.get("title_marks") or []):
                            sib_nos.add(str(x))
                    if sib_nos and sib_nos <= keys:
                        n["_notes_pool"] = {str(no): str(txt)
                                             for no, txt in k["notes"].items()}
                        n["_pool_source"] = k
                build(kids)
        build(chapters)
        # 2) 池上溯：仅当"归属本注释区来源"的引用出现在挂载点子树之外时上溯
        changed = True
        while changed:
            changed = False
            holders = [n for n in _walk_nodes(chapters) if n.get("_notes_pool")]
            for holder in holders:
                src = holder.get("_pool_source")
                if src is None:
                    continue
                pool_keys = set(holder["_notes_pool"])
                inside = {id(x) for x in subtree(holder)} | {id(holder)}
                ext = any(
                    no in pool_keys and id(rn) not in inside
                    and local_of.get(id(rn)) is src
                    for rn, no in refs)
                if not ext:
                    continue
                F = parents.get(id(holder))
                if F is None:
                    continue
                others = [x for x in (F.get("children") or [])
                          if x is not holder and x.get("_notes_pool")]
                if others:
                    continue
                F["_notes_pool"] = holder["_notes_pool"]
                F["_pool_source"] = src
                holder.pop("_notes_pool", None)
                holder.pop("_pool_source", None)
                changed = True

    # 注释池在两种模式下都启用（脚注模式同样需要跨节点配对）
    _promote_notes_pools(chapters)

    # —— 章末脚注渲染页准备 ——
    # 每篇注释集中渲染在"池子树最后一个有内容页"末尾：refs=该篇全部引用号、
    # back=各号首个引用页（返回链接用）、last_idx=渲染页页码（与 walk 一致）。
    _pidx = {}
    _pcnt = [0]
    def _scan_pidx(nodes):
        for n in nodes:
            if (n.get("content") or "").strip():
                _pcnt[0] += 1
                _pidx[id(n)] = _pcnt[0]
            _scan_pidx(n.get("children") or [])
    _scan_pidx(chapters)
    _all_refs = []
    def _sr2(nodes):
        for n in nodes:
            for m in re.finditer(r"[〔\[](\d{1,4})[〕\]]",
                                 n.get("content", "")):
                _all_refs.append((n, m.group(1)))
            for x in (n.get("title_marks") or []):
                _all_refs.append((n, str(x)))
            _sr2(n.get("children") or [])
    _sr2(chapters)
    def _subtree(n):
        out = []
        def s(nodes):
            for x in nodes:
                out.append(x)
                s(x.get("children") or [])
        s(n.get("children") or [])
        return out
    _pool_render = {}
    for _holder in [n for n in _walk_nodes(chapters) if n.get("_notes_pool")]:
        _hids = {id(x) for x in _subtree(_holder)} | {id(_holder)}
        _keys = set(_holder["_notes_pool"])
        _refs_no, _back = [], {}
        for _rn, _no in _all_refs:
            if _no in _keys and id(_rn) in _hids:
                if _no not in _back:
                    _back[_no] = _pidx.get(id(_rn), 1)
                if _no not in _refs_no:
                    _refs_no.append(_no)
        _refs_no.sort(key=lambda x: (not str(x).isdigit(),
                                     int(x) if str(x).isdigit() else 0))
        _last = None
        def _last_c(nodes):
            nonlocal _last
            for n in nodes:
                if (n.get("content") or "").strip():
                    _last = n
                _last_c(n.get("children") or [])
        _last_c([_holder])
        if _last is None:
            _last = _holder
        _pool_render[id(_holder)] = {
            "last_node": _last,
            "last_idx": _pidx.get(id(_last), 1),
            "refs": _refs_no,
            "back": _back,
        }

    def walk(node, ancestors, toc_children, inherited_gmap=None,
             inherited_notes=None, pool_node=None):
        label = (node["title"] or "未命名").strip()
        node_has_content = bool(node["content"].strip())
        t = _TocNode(label)
        toc_children.append(t)
        first_href = None
        # 注释表与全局编号（书末注模式）：池（父级共享）/ 继承 / 本节点
        notes = node.get("notes") or {}
        title_marks = node.get("title_marks") or []
        pool = node.get("_notes_pool")
        gmap = inherited_gmap
        if gmap is None and pool:
            # 共享注释池（两种模式都启用，解决"注释集中在某章/篇末、标记散布"
            # 的跨节点配对）：书末注用全书统一编号；章末脚注用注释区原号
            pool_node = node
            gmap = {}
            keys = sorted((k for k in pool if str(k).isdigit()), key=int)
            keys += [k for k in pool if not str(k).isdigit()]
            for no in keys:
                if endbook_mode:
                    gmap[str(no)] = next_global[0]
                    endbook_items.append((next_global[0], str(pool[no])))
                    next_global[0] += 1
                else:
                    gmap[str(no)] = str(no)
            eff_notes = pool
        elif gmap is not None:
            # 已继承池编号：注释文本同样继承（跨节点配对）
            eff_notes = inherited_notes if inherited_notes is not None else notes
        elif endbook_mode and (notes or title_marks):
            # 无共享池：本节点自己的注释编号
            gmap = {}
            keys = sorted((k for k in notes if str(k).isdigit()), key=int)
            keys += [k for k in notes if not str(k).isdigit()]
            for no in keys:
                gmap[str(no)] = next_global[0]
                endbook_items.append((next_global[0], str(notes[no])))
                next_global[0] += 1
            for no in title_marks:
                if no in gmap:
                    continue
                txt = str(notes.get(no, "")).strip()
                if not txt:
                    continue   # 文档缺失该注释文本：不生成空条目
                gmap[no] = next_global[0]
                endbook_items.append((next_global[0], txt))
                next_global[0] += 1
            eff_notes = notes
        else:
            eff_notes = notes
        if node_has_content:
            page_no[0] += 1
            idx = page_no[0]
            href = "chapter_%03d.xhtml" % idx
            t.href = href
            first_href = href
            w.add_manifest_item("chapter-%03d" % idx, href, "application/xhtml+xml")
            w.add_spine_item("chapter-%03d" % idx)
            # 页面正文：标题 + 层级路径 + 分段 + 注释
            crumb = " › ".join(escape_text(a) for a in ancestors) if ancestors else ""
            paras = paragraphs_from_text(node["content"], split_mode)
            html_paras, refs = [], []
            # 章末脚注：链接目标 = 本篇注释渲染页（池子树最后一个内容页）
            href_idx = None
            if pool_node is not None and not endbook_mode:
                href_idx = _pool_render.get(id(pool_node), {}).get("last_idx")
            # 标题 + 标题行注释角标（如"一　没有调查，没有发言权〔1〕"）
            title_html = escape_text(node["title"])
            for no in title_marks:
                txt = str(eff_notes.get(no, "")).strip()
                if not txt:
                    continue
                if gmap is not None and gmap.get(no):
                    g = gmap[no]
                    if not isinstance(g, int):
                        if no not in refs:
                            refs.append(no)
                        target = href_idx or idx
                        title_html += (
                            '<a epub:type="noteref" id="noteref-%d-%s" '
                            'href="chapter_%03d.xhtml#note-%d-%s">'
                            "<sup>〔%s〕</sup></a>"
                            % (idx, no, target, target, no, no)
                        )
                    else:
                        title_html += (
                            '<a epub:type="noteref" id="noteref-g%s" href="#note-g%s">'
                            "<sup>〔%s〕</sup></a>" % (g, g, g)
                        )
                elif no in eff_notes:
                    if no not in refs:
                        refs.append(no)
                    title_html += (
                        '<a epub:type="noteref" id="noteref-%d-%s" '
                        'href="chapter_%03d.xhtml#note-%d-%s">'
                        "<sup>〔%s〕</sup></a>"
                        % (idx, no, idx, idx, no, no)
                    )
                else:
                    title_html += "〔%s〕" % escape_text(no)
            body = "<h1>%s</h1>\n" % title_html
            if crumb:
                body += '<p style="font-size:0.85em;color:#777">%s</p>\n' % crumb
            if paras:
                for p in paras:
                    h, r = _linkify_paragraph(p, eff_notes, idx, gmap, href_idx)
                    html_paras.append(h)
                    for x in r:
                        if x not in refs:
                            refs.append(x)
            else:
                html_paras.append("<p></p>")
            body += "".join("<p>%s</p>\n" % p for p in html_paras)
            if not endbook_mode:
                rinfo = _pool_render.get(id(pool_node)) if pool_node is not None else None
                if rinfo is not None:
                    if node is rinfo["last_node"]:
                        # 本篇注释渲染页：完整列出本篇全部注释（跨节/跨章配对）
                        body += _chapter_notes_html(rinfo["refs"], eff_notes, idx,
                                                    rinfo["back"])
                    # 池内其他页：脚注区不渲染，角标统一指向本篇末渲染页
                elif refs:
                    # 无池页面（本节点自带注释表）：本页脚注区
                    body += _chapter_notes_html(refs, eff_notes, idx,
                                                {no: idx for no in refs})
            pages.append((idx, href, body))
        for child in node.get("children", []):
            fh = walk(child, ancestors + [node["title"]], t.children,
                      gmap, eff_notes if gmap is not None else None,
                      pool_node if gmap is not None else None)
            if first_href is None and fh:
                first_href = fh
        # 纯分类节点：指向其首个后代页面，保证目录可点
        if not node_has_content and first_href:
            t.href = first_href
        return first_href

    for node in chapters:
        walk(node, [], w.toc_tree)

    # 书末注释章节（endbook 模式）：置于全书末尾
    endnotes_href = None
    endnotes_html = ""
    if endbook_mode and endbook_items:
        endnotes_href = "endnotes.xhtml"
        items = []
        for g, text in endbook_items:
            items.append(
                '<aside epub:type="endnote" id="note-g%s">'
                "<p>〔%s〕%s</p>"
                '<p><a href="#noteref-g%s">↑ 返回正文</a></p>'
                "</aside>" % (g, g, escape_text(text), g)
            )
        endnotes_html = "<h1>注释</h1>\n" + "".join(items)
        w.add_manifest_item("endnotes", endnotes_href, "application/xhtml+xml")
        w.add_spine_item("endnotes")
        w.add_toc_node(_TocNode("注释", endnotes_href))

    if not pages:
        raise ValueError("书籍没有任何有正文的章节页面。")

    # 写入
    with w.open() as zf:
        w.add_container(zf)
        if cover_path:
            # 封面图片只作书架缩略图（meta name="cover"），不再生成独立封面页
            zf.write(str(cover_path), "OEBPS/images/cover" + cover_path.suffix.lower())
        zf.writestr("OEBPS/copyright.xhtml",
                    _xhtml_document("版权页", _copyright_xhtml(
                        title, authors, translators, publisher, pub_date, isbn)
                    ).encode("utf-8"))
        for idx, href, body in pages:
            zf.writestr("OEBPS/" + href,
                        _xhtml_document("", body, extra_head=extra_head).encode("utf-8"))
        if endnotes_href:
            zf.writestr("OEBPS/" + endnotes_href,
                        _xhtml_document("", endnotes_html, extra_head=extra_head).encode("utf-8"))
        w.write_nav(zf, title)
        w.write_ncx(zf, title)
        w.write_content_opf(zf, title, authors, translators, language, cover_item_id,
                            fixed_layout=fixed_layout,
                            publisher=publisher, pub_date=pub_date, isbn=isbn)
    return out_path


# ---------------------------------------------------------------------------
# 对外 API：漫画书
# ---------------------------------------------------------------------------

def build_comic_epub(out_path, title, authors, translators, language, image_paths,
                     cover_use_first=True, uid=None,
                     publisher=None, pub_date=None, isbn=None):
    """生成漫画 EPUB：每张图片一页，支持 JPG/PNG/GIF。

    image_paths: 有序图片路径列表（页码顺序 = 列表顺序）。
    cover_use_first: 是否将第一张图同时用作封面（默认 True）。
    publisher / pub_date / isbn: 可选版权信息（版权页 + OPF 元数据）。
    pub_date 支持 "2026" 或 "2026-10-03"，可留空。
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    uid = uid or _make_uid(title)
    w = _EpubWriter(out_path, uid)
    authors = _names(authors)
    translators = _names(translators)

    images = [Path(p) for p in image_paths]
    if not images:
        raise ValueError("漫画书至少需要一张图片。")

    # 校验图片格式
    for img in images:
        if not img.exists():
            raise FileNotFoundError("图片不存在：%s" % img)
        image_mime(img)

    cover_item_id = None
    first_href = "page_001.xhtml"
    if cover_use_first:
        cover_item_id = "cover-image"
        w.add_manifest_item(cover_item_id, "images/page_001" + images[0].suffix.lower(),
                            image_mime(images[0]), "cover-image")

    # 版权页（置于第一页之前）
    w.add_manifest_item("copyright", "copyright.xhtml", "application/xhtml+xml")
    w.add_spine_item("copyright")
    w.add_toc_node(_TocNode("版权页", "copyright.xhtml"))

    # 页面
    for idx, img in enumerate(images, start=1):
        href = "page_%03d.xhtml" % idx
        img_href = "images/page_%03d%s" % (idx, img.suffix.lower())
        w.add_manifest_item("page-%03d" % idx, href, "application/xhtml+xml")
        w.add_manifest_item("img-%03d" % idx, img_href, image_mime(img))
        w.add_spine_item("page-%03d" % idx)
        w.add_toc_node(_TocNode("第 %d 页" % idx, href))

    with w.open() as zf:
        w.add_container(zf)
        zf.writestr("OEBPS/copyright.xhtml",
                    _xhtml_document("版权页", _copyright_xhtml(
                        title, authors, translators, publisher, pub_date, isbn)
                    ).encode("utf-8"))
        for idx, img in enumerate(images, start=1):
            href = "page_%03d.xhtml" % idx
            img_href = "images/page_%03d%s" % (idx, img.suffix.lower())
            zf.write(str(img), "OEBPS/" + img_href)
            body = (
                '<div style="text-align:center;margin:0;padding:0">'
                '<img src="%s" alt="第 %d 页" '
                'style="max-width:100%%;height:auto;display:block;margin:0 auto"/></div>'
                % (img_href, idx)
            )
            zf.writestr("OEBPS/" + href,
                        _xhtml_document("第 %d 页" % idx, body).encode("utf-8"))
        w.write_nav(zf, title)
        w.write_ncx(zf, title)
        w.write_content_opf(zf, title, authors, translators, language, cover_item_id,
                            publisher=publisher, pub_date=pub_date, isbn=isbn)
    return out_path


# ---------------------------------------------------------------------------
# EPUB 解析（导入）
# ---------------------------------------------------------------------------

_XHTML_NS = "http://www.w3.org/1999/xhtml"
_EPUB_NS = "http://www.idpf.org/2007/ops"
_OPF_NS = "http://www.idpf.org/2007/opf"
_NCX_NS = "http://www.daisy.org/z3986/2005/ncx/"
_BLOCK_TAGS = {"p", "li", "blockquote", "h1", "h2", "h3", "h4", "h5", "h6"}


def _local(tag):
    """去掉 XML 命名空间前缀，返回裸标签名。"""
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _norm_zip_path(root_dir, href):
    """把 manifest/nav 里的相对 href 规整为 zip 内路径；含 .. 视为非法。"""
    if not href:
        return None
    href = href.replace("\\", "/")
    if href.startswith("/"):
        href = href.lstrip("/")
    parts = []
    for seg in href.split("/"):
        if seg in ("", "."):
            continue
        if seg == "..":
            return None
        parts.append(seg)
    if not parts:
        return None
    return (root_dir + "/" + "/".join(parts)).lstrip("/")


def _inner_text(elem, note_seq, skip_ids, unresolved=None):
    """元素内部纯文本；noteref 链接转 〔N〕 标记；<br> 转换行。
    unresolved（可选列表）用于收集跨文件未配对注释引用：
    [(目标文件名, frag, 链接原文)]，正文相应位置写入占位符。"""
    parts = []
    if elem.text:
        parts.append(elem.text)
    for ch in elem:
        if not isinstance(ch.tag, str):
            continue
        tag = _local(ch.tag)
        if tag == "aside" and ch.get("id") in skip_ids:
            pass
        elif tag == "a":
            href = ch.get("href") or ""
            frag = href.split("#")[-1] if "#" in href else ""
            if frag and frag in note_seq:
                parts.append("〔%d〕" % note_seq[frag])
            elif frag and unresolved is not None and "#" in href and href.split("#")[0].strip():
                # 未配对且指向其他文件：记录占位，等待跨文件配对
                fpart = href.split("#", 1)[0].strip()
                unresolved.append((fpart, frag, "".join(ch.itertext()).strip()))
                parts.append("\uE000%s#%s\uE001" % (fpart, frag))
            else:
                parts.append("".join(ch.itertext()))
        elif tag == "br":
            parts.append("\n")
        else:
            parts.append(_inner_text(ch, note_seq, skip_ids, unresolved))
        if ch.tail:
            parts.append(ch.tail)
    return "".join(parts)


def _collect_footnotes(body):
    """收集章节内注释（EPUB3 aside：footnote/rearnote/endnote；EPUB2 锚点式 div/p）。
    返回 (note_seq{id:序号}, notes{序号:文本}, id_map{id:序号})。"""
    refs = set()
    for a in body.iter():
        if isinstance(a.tag, str) and _local(a.tag) == "a":
            href = a.get("href") or ""
            if "#" in href:
                frag = href.split("#")[-1].strip()
                if frag:
                    refs.add(frag)
    footnotes = {}
    seq = [0]
    for el in body.iter():
        if not isinstance(el.tag, str):
            continue
        tag = _local(el.tag)
        if tag not in ("aside", "div", "section", "li", "p"):
            continue
        etype = el.get("{%s}type" % _EPUB_NS) or ""
        etypes = etype.split()
        nid = el.get("id") or ""
        is_note = any(t in etypes for t in ("footnote", "rearnote", "endnote", "noteref"))
        if not is_note and not etypes:
            # EPUB2 兜底：id 形如 fn1/note1 且被正文 <a href="#id"> 引用
            if nid and nid in refs and re.match(r"(?i)^(f|fn|foot|endnote|note|n)\d+$", nid):
                is_note = True
        if not is_note:
            continue
        if not nid:
            continue  # 无 id 无法配对，跳过
        seq[0] += 1
        txt = _inner_text(el, {}, set()).strip()
        # 清理注释装饰：开头的 〔N〕/序号前缀 与尾部"返回正文"导航链接
        txt = re.sub(r"^〔\d+〕\s*", "", txt)
        txt = re.sub(r"^\d+[\.、]\s*", "", txt)
        txt = re.sub(r"\s*[↑↩]?\s*返回正文\s*$", "", txt).strip()
        if nid:
            footnotes[nid] = (seq[0], txt)
    note_seq = {nid: num for nid, (num, _t) in footnotes.items()}
    notes = {str(num): txt for _nid, (num, txt) in footnotes.items()}
    return note_seq, notes, note_seq


def _extract_chapter(xhtml_bytes):
    """解析单个章节 XHTML -> (正文文本, 注释表, 首个标题, 未配对引用, id映射)。"""
    root = ET.fromstring(xhtml_bytes)
    body = root.find("{%s}body" % _XHTML_NS) or root
    note_seq, notes, id_map = _collect_footnotes(body)
    skip_ids = set(note_seq)
    unresolved = []
    blocks = []

    def collect(elem):
        for ch in elem:
            if not isinstance(ch.tag, str):
                continue
            tag = _local(ch.tag)
            if tag == "aside" and ch.get("id") in skip_ids:
                continue
            if tag in _BLOCK_TAGS:
                t = _inner_text(ch, note_seq, skip_ids, unresolved).strip()
                if t:
                    blocks.append(t)
            elif tag in ("div", "section", "article", "main"):
                collect(ch)
            elif tag not in ("style", "script", "title", "meta", "link", "head"):
                t = _inner_text(ch, note_seq, skip_ids, unresolved).strip()
                if t:
                    blocks.append(t)

    collect(body)
    title_hint = ""
    for ch in body.iter():
        if isinstance(ch.tag, str) and _local(ch.tag) in ("h1", "h2"):
            title_hint = "".join(ch.itertext()).strip()
            if title_hint:
                break
    return "\n\n".join(blocks), notes, title_hint, unresolved, id_map


def _parse_epub3_nav(xhtml_bytes, root_dir):
    """解析 EPUB3 nav.xhtml 嵌套目录 -> [{title, href, children}]。"""
    root = ET.fromstring(xhtml_bytes)
    body = root.find("{%s}body" % _XHTML_NS) or root
    ol = body.find(".//{%s}ol" % _XHTML_NS)
    if ol is None:
        return []

    def parse_list(o):
        nodes = []
        for li in o.findall("{%s}li" % _XHTML_NS):
            title, href = "", None
            for ch in li.iter():
                if isinstance(ch.tag, str) and _local(ch.tag) == "a" and ch.get("href"):
                    title = "".join(ch.itertext()).strip()
                    href = _norm_zip_path(root_dir, ch.get("href"))
                    break
            children = []
            sub = li.find("{%s}ol" % _XHTML_NS)
            if sub is not None:
                children = parse_list(sub)
            nodes.append({"title": title, "href": href, "children": children})
        return nodes

    return parse_list(ol)


def _parse_ncx(ncx_bytes, root_dir):
    """解析 EPUB2 toc.ncx 嵌套目录 -> [{title, href, children}]。"""
    root = ET.fromstring(ncx_bytes)
    nav_map = root.find("{%s}navMap" % _NCX_NS)
    if nav_map is None:
        return []

    def parse_map(parent):
        nodes = []
        for np in parent.findall("{%s}navPoint" % _NCX_NS):
            label = np.find("{%s}navLabel/{%s}text" % (_NCX_NS, _NCX_NS))
            content = np.find("{%s}content" % _NCX_NS)
            src = None
            if content is not None:
                src = _norm_zip_path(root_dir, content.get("src") or "")
            nodes.append({
                "title": label.text.strip() if label is not None and label.text else "",
                "href": src,
                "children": parse_map(np),
            })
        return nodes

    return parse_map(nav_map)


def parse_epub(epub_path, max_nodes=3000):
    """解析 EPUB 文件 -> BookForge 章节树与元数据。

    返回: {title, authors, translators, publisher, pub_date, isbn,
           chapters, note_count, warnings}
    chapters 为 [{title, content, notes, children}] 树结构（content 含自动识别的
    〔N〕 标记与章末注释表 notes）。目录层级取自 EPUB3 nav 或 EPUB2 NCX，
    缺失时按 spine 顺序平面导入（zipfile + ElementTree）。
    """
    epub_path = Path(epub_path)
    warnings = []
    try:
        zf = zipfile.ZipFile(epub_path)
    except Exception as exc:
        raise ValueError("无法打开 EPUB 文件：%s" % exc)

    # 1. container.xml -> content.opf 路径
    root_dir = "OEBPS"
    opf_path = "OEBPS/content.opf"
    try:
        container = ET.fromstring(zf.read("META-INF/container.xml"))
        for rf in container.iter():
            if _local(rf.tag) == "rootfile" and rf.get("full-path"):
                opf_path = rf.get("full-path")
                root_dir = opf_path.rsplit("/", 1)[0] if "/" in opf_path else ""
                break
    except Exception:
        pass

    # 2. content.opf：元数据 / manifest / spine
    try:
        opf = ET.fromstring(zf.read(opf_path))
    except KeyError:
        raise ValueError("EPUB 缺少 content.opf，无法解析。")
    except Exception as exc:
        raise ValueError("content.opf 解析失败：%s" % exc)

    title = ""
    creators = []          # [name, role]
    creator_ids = {}       # dc:creator id -> creators 下标
    publisher = pub_date = isbn = None
    for ch in opf.iter():
        tag = _local(ch.tag)
        if tag == "title" and not title:
            title = "".join(ch.itertext()).strip()
        elif tag == "creator":
            name = "".join(ch.itertext()).strip()
            if not name:
                continue
            role = (ch.get("{%s}role" % _OPF_NS) or "").lower()
            if role not in ("aut", "trl"):
                role = "aut"
            creators.append([name, role])
            cid = ch.get("id")
            if cid:
                creator_ids[cid] = len(creators) - 1
        elif tag == "publisher" and publisher is None:
            publisher = "".join(ch.itertext()).strip()
        elif tag == "date":
            val = "".join(ch.itertext()).strip()[:10]  # 保留完整日期（精确到日）
            if val and (ch.get("{%s}event" % _OPF_NS) == "publication" or pub_date is None):
                pub_date = val
        elif tag == "identifier" and isbn is None:
            scheme = (ch.get("scheme") or ch.get("{%s}scheme" % _OPF_NS) or "").upper()
            if scheme == "ISBN":
                isbn = "".join(ch.itertext()).strip()
    # EPUB3 风格：<meta refines="#creator-id" property="role">trl</meta>
    for m in opf.iter():
        if _local(m.tag) != "meta":
            continue
        if (m.get("property") or "") != "role":
            continue
        target = (m.get("refines") or "").lstrip("#")
        if target in creator_ids:
            role = (m.text or "").strip().lower()
            if role in ("aut", "trl"):
                creators[creator_ids[target]][1] = role
    authors = [n for n, r in creators if r == "aut"]
    translators = [n for n, r in creators if r == "trl"]

    manifest = {}
    nav_href = None
    for item in opf.iter():
        if _local(item.tag) != "item":
            continue
        iid = item.get("id")
        href = _norm_zip_path(root_dir, item.get("href") or "")
        if iid and href:
            manifest[iid] = href
        props = (item.get("properties") or "").split()
        if "nav" in props and not nav_href and href:
            nav_href = href

    spine_ids = []
    for item in opf.iter():
        if _local(item.tag) == "itemref":
            ref = item.get("idref")
            if ref and ref in manifest and ref not in spine_ids:
                spine_ids.append(ref)

    # 3. 目录树：优先 EPUB3 nav / EPUB2 NCX
    toc_tree = None
    ncx_id = None
    for iid, href in manifest.items():
        if iid.lower() == "ncx":
            ncx_id = href
            break
    for src in (nav_href, ncx_id):
        if not src:
            continue
        try:
            data = zf.read(src)
        except KeyError:
            continue
        try:
            if src == nav_href:
                toc_tree = _parse_epub3_nav(data, root_dir)
            else:
                toc_tree = _parse_ncx(data, root_dir)
            if toc_tree:
                break
        except Exception as exc:
            warnings.append("目录解析失败：%s" % exc)
            toc_tree = None

    # 4. 章节内容提取（同一文件只挂载一次）
    loaded = {}

    def load_file(href):
        if href in loaded:
            return loaded[href]
        try:
            data = zf.read(href)
        except (KeyError, ValueError):
            loaded[href] = None
            return None
        if data.startswith(b"\xef\xbb\xbf"):
            data = data[3:]
        try:
            text, notes, title_hint, unresolved, id_map = _extract_chapter(data)
            info = {"content": text, "notes": notes, "title_hint": title_hint,
                    "unresolved": unresolved, "id_map": id_map}
        except Exception as exc:
            warnings.append("章节解析失败：%s（%s）" % (href, exc))
            info = {"content": "", "notes": {}, "title_hint": "",
                    "unresolved": [], "id_map": {}}
        loaded[href] = info
        return info

    # 4.1 预加载全部章节文件（目录引用 + spine），再做跨文件注释配对
    if toc_tree:
        def walk_hrefs(nodes):
            for n in nodes:
                if n.get("href"):
                    load_file(n["href"].split("#")[0])
                walk_hrefs(n.get("children") or [])
        walk_hrefs(toc_tree)
    for ref in spine_ids:
        if ref in manifest:
            load_file(manifest[ref])

    for href, info in loaded.items():
        if not info or not info.get("unresolved"):
            continue
        for fpart, frag, orig in info["unresolved"]:
            target = _norm_zip_path(root_dir, fpart) if fpart else None
            ti = loaded.get(target) or (loaded.get(fpart) if fpart else None)
            num = (ti or {}).get("id_map", {}).get(frag) if ti else None
            marker = "\uE000%s#%s\uE001" % (fpart, frag)
            if num is not None and ti and str(num) in ti.get("notes", {}):
                nxt = 1 + max((int(k) for k in info["notes"]), default=0)
                info["content"] = info["content"].replace(marker, "〔%d〕" % nxt)
                info["notes"][str(nxt)] = ti["notes"][str(num)]
            else:
                info["content"] = info["content"].replace(marker, orig)

    used_files = set()
    note_count = [0]
    pending = {}  # fpath -> [nodes...]（按目录顺序）

    def build_tree(toc_nodes):
        out = []
        for n in toc_nodes:
            href = n.get("href")
            if href:
                fpath = href.split("#")[0]
                info = load_file(fpath)
            else:
                info = None
            title = n.get("title") or (info or {}).get("title_hint") or "未命名"
            node = {
                "title": title,
                "content": "",
                "notes": {},
                "children": [],
            }
            # 先注册父节点，再递归子节点（保证目录顺序 = 引用顺序）
            if info and fpath:
                pending.setdefault(fpath, []).append(node)
            node["children"] = build_tree(n.get("children") or [])
            out.append(node)
        return out

    if toc_tree:
        chapters = build_tree(toc_tree)
        # 同一文件被多个目录项引用（如"卷"指向首个后代页）时，
        # 正文挂到最后引用它的条目（真正的章节标题节点）
        for fpath, nodes in pending.items():
            info = loaded.get(fpath)
            if not info:
                continue
            target = nodes[-1]
            target["content"] = info["content"]
            target["notes"] = info["notes"]
            note_count[0] += len(info["notes"])
            # 诊断：正文有〔N〕标记但无对应注释内容（源文件注释残缺）
            marks = len(re.findall(r"〔\d+〕", info["content"]))
            if marks > len(info["notes"]):
                warnings.append("《%s》：正文含 %d 个注释标记，但源文件中缺少对应注释正文（该书稿注释残缺）"
                                % ((target["title"] or "未命名"), marks - len(info["notes"])))
            # 正文首段若与节点标题相同则剥离（避免页内重复标题）
            content = info["content"]
            if content:
                first = content.split("\n\n", 1)[0]
                if target["title"] and first == target["title"]:
                    rest = content[len(first) + 2:] if len(content) > len(first) else ""
                    target["content"] = rest
    else:
        chapters = []
        for ref in spine_ids:
            href = manifest[ref]
            info = load_file(href)
            ch_title = ((info or {}).get("title_hint") or href.rsplit("/", 1)[-1])
            content = (info or {}).get("content", "") if href not in used_files else ""
            notes = (info or {}).get("notes", {})
            if href not in used_files:
                used_files.add(href)
                note_count[0] += len(notes)
            marks = len(re.findall(r"〔\d+〕", content))
            if marks > len(notes):
                warnings.append("《%s》：正文含 %d 个注释标记，但源文件中缺少对应注释正文（该书稿注释残缺）"
                                % (ch_title, marks - len(notes)))
            chapters.append({
                "title": ch_title,
                "content": content,
                "notes": notes,
                "children": [],
            })

    def count_nodes(nodes):
        return 1 + sum(count_nodes(n.get("children") or []) for n in nodes)

    if not chapters:
        raise ValueError("EPUB 中没有可导入的章节内容。")
    if count_nodes(chapters) > max_nodes:
        raise ValueError("EPUB 目录项超过 %d 个，无法导入。" % max_nodes)

    return {
        "title": title,
        "authors": authors,
        "translators": translators,
        "publisher": publisher,
        "pub_date": pub_date,
        "isbn": isbn,
        "chapters": chapters,
        "note_count": note_count[0],
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# DOCX 解析导入（zipfile + ElementTree）
# ---------------------------------------------------------------------------

_DOCX_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_DOCX_CP_NS = "http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
_DOCX_DC_NS = "http://purl.org/dc/elements/1.1/"


def _docx_attr(el, name):
    """读 w: 命名空间属性（如 w:id / w:val），兼容无命名空间写法。"""
    return el.get("{%s}%s" % (_DOCX_W_NS, name)) or el.get(name)


def _docx_paragraphs(root):
    """按文档顺序收集 body 下非表格内的 w:p。"""
    body = None
    for el in root.iter():
        if _local(el.tag) == "body":
            body = el
            break
    if body is None:
        return []
    paras = []

    def walk(el):
        for child in el:
            tag = _local(child.tag)
            if tag == "tbl":
                continue  # 表格整体跳过
            if tag == "p":
                paras.append(child)
            else:
                walk(child)
    walk(body)
    return paras


def _docx_para_text(p, refs):
    """提取段落文本：合并 run 文本，<w:br/> 视为段内换行，脚注引用还原为 〔N〕。"""
    parts = []

    def walk(el):
        tag = _local(el.tag)
        if tag == "t":
            parts.append(el.text or "")
        elif tag == "br":
            parts.append("\n")
        elif tag == "tab":
            parts.append("\t")
        elif tag == "footnoteReference":
            fid = _docx_attr(el, "id")
            if fid:
                parts.append("〔%s〕" % fid)
                refs.add(fid)
        else:
            for c in el:
                walk(c)

    for c in p:
        walk(c)
    return "".join(parts)


def _docx_footnotes(root):
    """读取 word/footnotes.xml 的脚注内容（跳过 id 0/1 分隔符）。"""
    notes = {}
    for fn in root.iter():
        if _local(fn.tag) != "footnote":
            continue
        fid = _docx_attr(fn, "id")
        if not fid or fid in ("0", "1"):
            continue
        texts = []
        for p in fn.iter():
            if _local(p.tag) != "p":
                continue
            t = _docx_para_text(p, set())
            if t.strip():
                texts.append(t)
        notes[fid] = "\n\n".join(texts)
    return notes


_CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"
_CIRCLED_MAP = {ch: i + 1 for i, ch in enumerate(_CIRCLED)}


def _extract_plain_notes(content):
    """对纯文本正文做注释感知（对齐前端 parseTxt 语义，并支持无"注释"标题行的〔N〕注释区）。

    返回 (body, notes, problems, note_count)：注释区从正文剥离进 notes 表，
    正文中已配对的 〔N〕/[N]/圈号 统一为 〔N〕 外观。"""
    notes = {}
    problems = []
    body_lines = []
    in_notes = False
    for raw in content.split("\n"):
        line = raw.strip()
        if not line:
            continue
        # 注释区标题行：注释 / 注 / 【注释】 / 注释：
        if not in_notes and re.match(r"^[【\[]?(注释|注|脚注)[】\]]?[：:]?$", line):
            in_notes = True
            continue
        m_entry = re.match(r"^[〔\[](\d{1,4})[〕\]](.*)$", line)
        m_circle = re.match(r"^([①-⑳])(.*)$", line)
        if m_entry or m_circle:
            no = m_entry.group(1) if m_entry else str(_CIRCLED_MAP[m_circle.group(1)])
            tail = (m_entry.group(2) if m_entry else m_circle.group(2)).strip()
            if no in notes:
                problems.append("注释 %s 重复定义，已覆盖" % no)
            notes[no] = tail
            in_notes = True
            continue
        if in_notes:
            if re.match(r"^（.+）$", line):
                # 整行圆括号括注（题解/编者说明）：注释区结束，归为正文
                in_notes = False
                body_lines.append(line)
            elif notes:
                notes[list(notes)[-1]] += "\n" + line  # 注释多行续接
            else:
                body_lines.append(line)
            continue
        body_lines.append(line)

    def norm(line):
        def repl(m):
            return "〔%s〕" % m.group(1) if m.group(1) in notes else m.group(0)
        out = re.sub(r"[〔\[](\d{1,4})[〕\]]", repl, line)

        def circ(ch):
            n = _CIRCLED_MAP.get(ch)
            return "〔%d〕" % n if n and str(n) in notes else ch
        out = re.sub(r"[①-⑳]", lambda m: circ(m.group(0)), out)
        return out

    body = "\n\n".join(norm(l) for l in body_lines)
    return body, notes, problems, len(notes)


def _docx_styles(root):
    """styles.xml：styleId -> 样式名称（用于标题识别）。"""
    mapping = {}
    for st in root.iter():
        if _local(st.tag) != "style":
            continue
        sid = _docx_attr(st, "styleId")
        name = None
        for el in st.iter():
            if _local(el.tag) == "name":
                name = _docx_attr(el, "val")
                break
        if sid:
            mapping[sid] = name or ""
    return mapping


def _docx_heading_level(p, style_names):
    """返回标题层级 1-9；非标题返回 0。优先样式名称，其次 styleId，数字 id 兜底。"""
    pPr = next((c for c in p if _local(c.tag) == "pPr"), None)
    if pPr is None:
        return 0
    style = None
    for el in pPr:
        if _local(el.tag) == "pStyle":
            style = _docx_attr(el, "val")
            break
    if not style:
        return 0
    s = style.strip()
    name = style_names.get(s, "")
    m = re.match(r"^(?:标题|Heading)\s*(\d)$", name, re.IGNORECASE)
    if m:
        return int(m.group(1))
    m = re.match(r"^(?:heading|标题)\s*(\d)$", s, re.IGNORECASE)
    if m:
        return int(m.group(1))
    if re.match(r"^\d$", s):
        if name and ("标题" in name or "heading" in name.lower()):
            return int(s)
        if not style_names:  # 无 styles.xml 时的兜底
            return int(s)
    return 0


def parse_docx(docx_path, max_nodes=3000):
    """解析 DOCX -> BookForge 章节树与元数据。

    返回: {title, authors, translators, publisher, pub_date, isbn,
           chapters, note_count, warnings}
    - 标题（Heading1-9 / 标题 1-9 及常见 styleId）建立多级目录树，正文归入最近标题。
    - 段落文本合并多个 run；<w:br/> 视为段内换行；空段落保留（供"空行分段"使用）。
    - 脚注（word/footnotes.xml）自动还原为 〔N〕 角标 + 章末注释表。
    - 元数据取 docProps/core.xml 的标题与著者。
    """
    docx_path = Path(docx_path)
    warnings = []
    try:
        zf = zipfile.ZipFile(docx_path)
    except zipfile.BadZipFile:
        raise ValueError("文件不是有效的 DOCX（无法作为 zip 打开）。")
    with zf:
        try:
            doc_root = ET.fromstring(zf.read("word/document.xml"))
        except KeyError:
            raise ValueError("DOCX 缺少 word/document.xml，无法解析。")
        except ET.ParseError as exc:
            raise ValueError("DOCX 正文 XML 解析失败：%s" % exc)

        footnotes = {}
        try:
            fn_root = ET.fromstring(zf.read("word/footnotes.xml"))
            footnotes = _docx_footnotes(fn_root)
        except (KeyError, ET.ParseError):
            pass  # 无脚注文件

        style_names = {}
        try:
            st_root = ET.fromstring(zf.read("word/styles.xml"))
            style_names = _docx_styles(st_root)
        except (KeyError, ET.ParseError):
            pass

        title = ""
        authors = []
        try:
            cp = ET.fromstring(zf.read("docProps/core.xml"))
            t = cp.find("{%s}title" % _DOCX_DC_NS)
            if t is not None and t.text and t.text.strip():
                title = t.text.strip()
            for c in cp.findall("{%s}creator" % _DOCX_DC_NS):
                if c.text and c.text.strip():
                    authors.append(c.text.strip())
        except (KeyError, ET.ParseError):
            pass

    # ---- 建树：标题 -> 层级节点；正文 -> 最近标题的 content ----
    root_children = []
    stack = []               # [(level, node)]
    current = None           # 当前内容节点
    node_count = 0
    note_count = 0
    for p in _docx_paragraphs(doc_root):
        refs = set()
        text = _docx_para_text(p, refs)
        level = _docx_heading_level(p, style_names)
        if level > 0:
            t = text.strip() or "（无标题）"
            # 标题行中的注释标记（如"一　没有调查，没有发言权〔1〕"）剥离并登记，
            # 生成时渲染为注释角标链接（与正文 〔N〕 同等对待）。
            title_marks = []
            for m in re.finditer(r"[〔\[](\d{1,4})[〕\]]", t):
                title_marks.append(m.group(1))
            for m in re.finditer(r"[①-⑳]", t):
                title_marks.append(str(_CIRCLED_MAP[m.group(0)]))
            t_clean = re.sub(r"[〔\[]\d{1,4}[〕\]]", "", t)
            t_clean = re.sub(r"[①-⑳]", "", t_clean).strip() or "（无标题）"
            node = {"title": t_clean, "content": "", "notes": {},
                    "title_marks": title_marks, "children": []}
            while stack and stack[-1][0] >= level:
                stack.pop()
            if stack:
                stack[-1][1]["children"].append(node)
            else:
                root_children.append(node)
            stack.append((level, node))
            current = node
            node_count += 1
            if node_count > max_nodes:
                warnings.append("目录项超过 %d 个，已截断。" % max_nodes)
                break
        else:
            if current is None:
                node = {"title": "正文", "content": "", "notes": {}, "children": []}
                root_children.append(node)
                stack.append((1, node))
                current = node
                node_count += 1
            if text == "":
                current["content"] += "\n\n"
            elif current["content"]:
                current["content"] += "\n\n" + text
            else:
                current["content"] = text
            for fid in refs:
                body = footnotes.get(fid)
                if body is None:
                    continue
                if len(body) > 50000:
                    body = body[:50000]
                if fid not in current["notes"]:
                    current["notes"][fid] = body
                    note_count += 1

    # ---- 纯文本注释感知：正文里 〔N〕 标记 + 注释区（用户手打样式，无 Word 脚注）----
    # 以解析出的网页正文文本为准：注释区提取进 notes 表，正文保留配对后的 〔N〕 标记。
    for n in _walk_nodes(root_children):
        content = n.get("content", "")
        if n.get("notes"):
            continue  # 已有 Word 脚注的章节不重复解析
        if not re.search(r"[〔\[]\d{1,4}[〕\]]|[①-⑳]", content):
            continue
        body, notes, problems, nc = _extract_plain_notes(content)
        if notes:
            n["content"] = body
            n["notes"] = notes
            n["_plain_notes"] = True   # 纯文本注释区节点（书末注模式"篇级注释池"候选）
            note_count += nc
            for pr in problems:
                warnings.append("《%s》%s" % (n["title"], pr))

    def count_nodes(nodes):
        return 1 + sum(count_nodes(n.get("children") or []) for n in nodes)

    if not root_children or not any(
            n.get("content", "").strip() for n in _walk_nodes(root_children)):
        raise ValueError("DOCX 中没有可导入的正文内容。")

    return {
        "title": title,
        "authors": authors,
        "translators": [],
        "publisher": None,
        "pub_date": None,
        "isbn": None,
        "chapters": root_children,
        "note_count": note_count,
        "warnings": warnings,
    }


def _walk_nodes(nodes):
    for n in nodes:
        yield n
        yield from _walk_nodes(n.get("children") or [])
