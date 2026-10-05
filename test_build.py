# -*- coding: utf-8 -*-
"""BookForge 回归测试：生成示例书籍到 output/，并校验 EPUB 结构合法性。

运行：python test_build.py
"""
import re
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import epub_builder

BASE = Path(__file__).resolve().parent
TESTDATA = BASE / "testdata"
OUT = BASE / "output"


def verify(epub: Path, expect_spine: int):
    with zipfile.ZipFile(epub) as zf:
        names = zf.namelist()
        assert names[0] == "mimetype", "mimetype 必须第一个写入"
        assert zf.getinfo("mimetype").compress_type == zipfile.ZIP_STORED, \
            "mimetype 必须不压缩"
        assert zf.read("mimetype") == b"application/epub+zip"
        for required in ("META-INF/container.xml", "OEBPS/content.opf",
                         "OEBPS/nav.xhtml", "OEBPS/toc.ncx"):
            assert required in names, "缺少 %s" % required
        opf = zf.read("OEBPS/content.opf").decode("utf-8")
        refs = re.findall(r"<itemref", opf)
        assert len(refs) == expect_spine, \
            "spine itemref 数量不符：期望 %d，实际 %d" % (expect_spine, len(refs))
        # 所有 spine 引用的 item 必须存在于 manifest
        item_ids = set(re.findall(r'<item id="([^"]+)"', opf))
        idrefs = set(re.findall(r'<itemref idref="([^"]+)"', opf))
        assert idrefs <= item_ids, "spine 引用了 manifest 之外的 item"
        print("    校验通过: spine=%d, 文件数=%d" % (expect_spine, len(names)))


def test_text_book():
    chapters = [
        ("第一章 相遇",
         "雨下得很大。\n他撑着一把旧伞，站在街角。\n\n她推门出来，看见了他。\n\n"
         "两个人隔着雨幕，谁也没有先开口。"),
        ("第二章 告别",
         "火车缓缓开动。\n\n站台上的人影越来越小，最后消失在晨雾里。\n\n"
         "他忽然想起，那天的伞，其实一直握在自己手里。"),
    ]
    out = OUT / "示例文字书.epub"
    epub_builder.build_text_epub(out, "示例文字书", "BookForge 测试", [], "zh", chapters)
    verify(out, expect_spine=3)  # 版权页 + 2 章
    print("[OK] 文字书:", out)


def test_comic_book():
    pages = sorted(TESTDATA.glob("page*.png"))
    assert pages, "testdata 中没有测试图片"
    out = OUT / "示例漫画.epub"
    epub_builder.build_comic_epub(out, "示例漫画", "BookForge 测试", [], "zh", pages)
    verify(out, expect_spine=len(pages) + 1)  # 版权页 + N 页漫画
    print("[OK] 漫画书:", out)


def test_sanitize():
    assert epub_builder.sanitize_filename('a/\\:*?"<>|b') == "a_________b"
    assert epub_builder.sanitize_filename("..") == "book"
    print("[OK] 文件名清理")


def test_paragraphs():
    ps = epub_builder.paragraphs_from_text("a\nb\n\nc")
    assert ps == ["a b", "c"], ps
    print("[OK] 段落切分")


def test_nested_tree():
    """多级目录：卷 → 篇 → 章 → 节，含纯分类节点。"""
    chapters = [
        {"title": "第一卷", "content": "", "children": [
            {"title": "第一篇", "content": "篇首说明文字。", "children": [
                {"title": "第一章", "content": "正文一。\n\n正文二。", "children": []},
                {"title": "第二章", "content": "正文三。", "children": []},
            ]},
            {"title": "第二篇", "content": "", "children": [
                {"title": "第三章", "content": "正文四。", "children": [
                    {"title": "第一节", "content": "小节内容。", "children": []},
                ]},
            ]},
        ]},
        {"title": "第二卷", "content": "卷首语。", "children": []},
    ]
    out = OUT / "示例多级目录.epub"
    epub_builder.build_text_epub(out, "示例多级目录", "BookForge 测试", [], "zh", chapters)
    verify(out, expect_spine=7)  # 版权页 + 6 页（篇一/章一/章二/章三/节一/卷二卷首）
    with zipfile.ZipFile(out) as zf:
        nav = zf.read("OEBPS/nav.xhtml").decode("utf-8")
        ncx = zf.read("OEBPS/toc.ncx").decode("utf-8")
        assert nav.count("<ol>") >= 3, "nav 应有多级嵌套"
        assert nav.count("<li>") == 9, "nav 应有 9 个目录条目（含版权页）"
        assert ncx.count("<navMap>") >= 3, "NCX 应有多级嵌套"
        assert ncx.count("<navPoint") == 9, "NCX 应有 9 个 navPoint（含版权页）"
        # 纯分类节点（第一卷）应指向其后代页面
        import re
        vol1_href = re.search(r'<li><a href="(chapter_\d+\.xhtml)">第一卷</a>', nav)
        assert vol1_href, "第一卷应可点击且指向首个后代页面"
        # 页面正文应包含层级路径（面包屑）
        ch2 = zf.read("OEBPS/chapter_002.xhtml").decode("utf-8")
        assert "第一卷" in ch2 and "第一篇" in ch2, "页面应含层级路径"
        ch3 = zf.read("OEBPS/chapter_003.xhtml").decode("utf-8")
        assert "第一卷" in ch3 and "第一篇" in ch3, "页面应含层级路径"
        ch4 = zf.read("OEBPS/chapter_004.xhtml").decode("utf-8")
        assert "第一卷" in ch4 and "第二篇" in ch4, "页面应含层级路径"
    print("[OK] 多级目录:", out)


def test_notes_footnotes():
    """章末脚注：正文〔N〕标记 -> noteref 链接，章末生成 footnotes 区与返回链接。"""
    chapters = [
        {"title": "第一章", "content": "正文提到甲〔1〕和乙〔2〕，还有未配对的〔99〕。",
         "notes": {"1": "注释一内容。", "2": "注释二内容。"}, "children": []},
        {"title": "第二章", "content": "引用同一注释〔1〕。",
         "notes": {"1": "注释一内容。"}, "children": []},
    ]
    out = OUT / "示例注释书.epub"
    epub_builder.build_text_epub(out, "示例注释书", "BookForge 测试", [], "zh", chapters)
    verify(out, expect_spine=3)  # 版权页 + 2 章
    with zipfile.ZipFile(out) as zf:
        ch1 = zf.read("OEBPS/chapter_001.xhtml").decode("utf-8")
        ch2 = zf.read("OEBPS/chapter_002.xhtml").decode("utf-8")
        # 正文链接：noteref 指向注释锚点（跨文件格式，兼容阅读器跳转）
        assert 'epub:type="noteref"' in ch1
        assert ('href="chapter_001.xhtml#note-1-1"' in ch1
                and 'href="chapter_001.xhtml#note-1-2"' in ch1)
        # 未配对标记保留原样且不生成链接
        assert "〔99〕" in ch1 and "note-1-99" not in ch1
        # 章末注释区
        assert 'epub:type="footnotes"' in ch1
        assert 'id="note-1-1"' in ch1 and 'id="note-1-2"' in ch1
        assert "注释一内容" in ch1 and "注释二内容" in ch1
        assert "返回正文" in ch1
        # 第二章引用编号 1 的注释，锚点带章节前缀避免冲突
        assert 'href="chapter_002.xhtml#note-2-1"' in ch2 and 'id="note-2-1"' in ch2
        assert 'id="note-1-1"' not in ch2
        # 目录不含注释区（注释只在章末，不进 TOC）
        nav = zf.read("OEBPS/nav.xhtml").decode("utf-8")
        assert "返回正文" not in nav and "footnotes" not in nav
    print("[OK] 章末脚注:", out)


def test_multi_creators():
    """多人著者与译者：dc:creator 多条目且 role 正确（aut/trl）。"""
    chapters = [{"title": "第一章", "content": "正文。", "children": []}]
    out = OUT / "示例多人元数据.epub"
    epub_builder.build_text_epub(
        out, "示例多人元数据",
        ["马克思", "恩格斯"], ["郭大力", "王亚南"], "zh", chapters)
    verify(out, expect_spine=2)  # 版权页 + 1 章
    with zipfile.ZipFile(out) as zf:
        opf = zf.read("OEBPS/content.opf").decode("utf-8")
        aut = re.findall(r'<dc:creator opf:role="aut">([^<]+)</dc:creator>', opf)
        trl = re.findall(r'<dc:creator opf:role="trl">([^<]+)</dc:creator>', opf)
        assert aut == ["马克思", "恩格斯"], aut
        assert trl == ["郭大力", "王亚南"], trl
    # 兼容：传单个字符串
    out2 = OUT / "示例单作者.epub"
    epub_builder.build_text_epub(out2, "示例单作者", "单一作者", [], "zh", chapters)
    with zipfile.ZipFile(out2) as zf:
        opf2 = zf.read("OEBPS/content.opf").decode("utf-8")
        assert re.findall(r'<dc:creator opf:role="aut">([^<]+)</dc:creator>', opf2) == ["单一作者"]
        assert "trl" not in opf2
    print("[OK] 多人著者/译者:", out)


def test_copyright_page():
    """版权页：spine 含 copyright 页；OPF 含 publisher/date/ISBN；nav 含条目。"""
    chapters = [{"title": "第一章", "content": "正文。", "children": []}]
    out = OUT / "示例版权页.epub"
    epub_builder.build_text_epub(out, "示例版权页", ["作者甲"], ["译者乙"], "zh",
                                 chapters, publisher="人民出版社", pub_date="2026-10-03",
                                 isbn="978-7-01-000000-0")
    verify(out, expect_spine=2)  # 版权页 + 第一章
    with zipfile.ZipFile(out) as zf:
        assert "OEBPS/copyright.xhtml" in zf.namelist()
        opf = zf.read("OEBPS/content.opf").decode("utf-8")
        assert "<dc:publisher>人民出版社</dc:publisher>" in opf
        assert '<dc:date opf:event="publication">2026-10-03</dc:date>' in opf
        assert 'opf:scheme="ISBN">978-7-01-000000-0<' in opf
        assert "copyright.xhtml" in zf.read("OEBPS/nav.xhtml").decode("utf-8")
        cp = zf.read("OEBPS/copyright.xhtml").decode("utf-8")
        assert "人民出版社" in cp and "ISBN" in cp and "版权所有，翻版必究" in cp
        assert "©" not in cp
        assert "出版时间：2026年10月3日" in cp
    print("[OK] 版权页:", out)


def test_import_epub():
    """EPUB 导入（自举）：生成含多级目录/注释/多人元数据的书，再解析回读。"""
    chapters = [
        {"title": "第一卷", "content": "", "children": [
            {"title": "第一章", "content": "首段内容〔1〕和〔2〕。\n\n第二段。",
             "notes": {"1": "注释一", "2": "注释二"}, "children": []},
            {"title": "第二章", "content": "第二章正文。", "children": []},
        ]},
    ]
    out = OUT / "示例导入源.epub"
    epub_builder.build_text_epub(out, "示例导入书", ["作者甲", "作者乙"],
                                 ["译者丙"], "zh", chapters,
                                 publisher="人民出版社", pub_date="2026-10-03",
                                 isbn="978-7-01-000000-0")
    m = epub_builder.parse_epub(out)
    assert m["title"] == "示例导入书", m["title"]
    assert m["authors"] == ["作者甲", "作者乙"]
    assert m["translators"] == ["译者丙"]
    assert m["publisher"] == "人民出版社" and m["pub_date"] == "2026-10-03"
    assert m["isbn"] == "978-7-01-000000-0"
    tops = [c["title"] for c in m["chapters"]]
    assert "第一卷" in tops
    v1 = next(c for c in m["chapters"] if c["title"] == "第一卷")
    assert v1["content"] == "" and len(v1["children"]) == 2
    c1 = v1["children"][0]
    assert c1["title"] == "第一章"
    assert c1["notes"] == {"1": "注释一", "2": "注释二"}, c1["notes"]
    assert "〔1〕" in c1["content"] and "〔2〕" in c1["content"]
    assert m["note_count"] == 2
    assert not m["warnings"], m["warnings"]
    print("[OK] EPUB 导入（自举回读）:", out)


def test_layout_modes():
    """排版：中文默认（缩进 + 回车换段）与英文默认（无缩进 + 空行分段）。"""
    # 段落切分模式
    text = "第一行。\n第二行。\n\n第三段。"
    assert len(epub_builder.paragraphs_from_text(text, "blank")) == 2
    assert len(epub_builder.paragraphs_from_text(text, "line")) == 3
    # 中文默认：每行一段 + 缩进样式
    ch_zh = [{"title": "章", "content": "第一行。\n第二行。", "children": []}]
    zh = OUT / "示例中文排版.epub"
    epub_builder.build_text_epub(zh, "示例中文排版", "作者", [], "zh", ch_zh,
                                 indent_2em=True, split_mode="line")
    with zipfile.ZipFile(zh) as zf:
        html = zf.read("OEBPS/chapter_001.xhtml").decode("utf-8")
        assert html.count("<p>") == 2, "回车换段应生成 2 个段落"
        assert "text-indent:2em" in html, "应含首行缩进样式"
    # 英文默认：空行分段 + 无缩进
    ch_en = [{"title": "Ch", "content": "First line.\nSecond line.", "children": []}]
    en = OUT / "示例英文排版.epub"
    epub_builder.build_text_epub(en, "Example", "Author", [], "en", ch_en,
                                 indent_2em=False, split_mode="blank")
    with zipfile.ZipFile(en) as zf:
        html = zf.read("OEBPS/chapter_001.xhtml").decode("utf-8")
        assert html.count("<p>") == 1, "空行分段应把两行合并为一个段落"
        assert "text-indent" not in html, "不应有缩进样式"
    print("[OK] 中英文排版模式:", zh, "|", en)


def test_pubdate_year_only():
    """出版时间仅年份：dc:date 输出年份；版权页显示年份；留空则不显示。"""
    ch = [{"title": "章", "content": "正文。", "children": []}]
    out = OUT / "示例仅年份.epub"
    epub_builder.build_text_epub(out, "仅年份书", "作者", [], "zh", ch,
                                 publisher="人民出版社", pub_date="2026")
    with zipfile.ZipFile(out) as zf:
        opf = zf.read("OEBPS/content.opf").decode("utf-8")
        assert "<dc:date>2026</dc:date>" in opf
        assert "opf:event" not in opf.split("<dc:date>2026</dc:date>")[0][-50:]
        cp = zf.read("OEBPS/copyright.xhtml").decode("utf-8")
        assert "出版时间：2026" in cp and "出版时间：2026年" not in cp
    # 留空：版权页无出版时间行
    out2 = OUT / "示例无时间.epub"
    epub_builder.build_text_epub(out2, "无时间书", "作者", [], "zh", ch)
    with zipfile.ZipFile(out2) as zf:
        cp = zf.read("OEBPS/copyright.xhtml").decode("utf-8")
        assert "出版时间" not in cp
        opf = zf.read("OEBPS/content.opf").decode("utf-8")
        assert "dc:date" not in opf
    print("[OK] 仅年份/留空出版时间:", out, "|", out2)


def _make_docx(path):
    """手工构造一个最小 DOCX：两级标题 + 多 run 文本 + 换行 + 脚注 + 表格 + 元数据。"""
    doc = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:body>
<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>第一卷</w:t></w:r></w:p>
<w:p><w:r><w:t>卷首语。</w:t></w:r></w:p>
<w:p><w:pPr><w:pStyle w:val="Heading2"/></w:pPr><w:r><w:t>第一章</w:t></w:r></w:p>
<w:p><w:r><w:t>第一段正文</w:t></w:r><w:r><w:br/></w:r><w:r><w:t>换行继续</w:t></w:r></w:p>
<w:p><w:r><w:t>带脚注的内容</w:t></w:r><w:r><w:footnoteReference w:id="3"/></w:r></w:p>
<w:p/>
<w:p><w:r><w:t>空行后的段落。</w:t></w:r></w:p>
<w:tbl><w:tr><w:tc><w:p><w:r><w:t>表格内文字不应进入正文</w:t></w:r></w:p></w:tc></w:tr></w:tbl>
</w:body>
</w:document>'''
    foot = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:footnotes xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:footnote w:type="separator" w:id="0"><w:p><w:r><w:t>---</w:t></w:r></w:p></w:footnote>
<w:footnote w:type="continuationSeparator" w:id="1"><w:p/></w:footnote>
<w:footnote w:id="3"><w:p><w:r><w:t>这是第三条注释。</w:t></w:r></w:p></w:footnote>
</w:footnotes>'''
    styles = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="标题 1"/></w:style>
<w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="标题 2"/></w:style>
</w:styles>'''
    core = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
 xmlns:dc="http://purl.org/dc/elements/1.1/">
<dc:title>示例 Word 书稿</dc:title>
<dc:creator>张三</dc:creator>
<dc:creator>李四</dc:creator>
</cp:coreProperties>'''
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("word/document.xml", doc)
        zf.writestr("word/footnotes.xml", foot)
        zf.writestr("word/styles.xml", styles)
        zf.writestr("docProps/core.xml", core)


def test_import_docx():
    """DOCX 导入：标题层级树、多 run 文本合并、脚注转注释、表格跳过、元数据。"""
    p = OUT / "示例书稿.docx"
    _make_docx(p)
    m = epub_builder.parse_docx(p)
    assert m["title"] == "示例 Word 书稿", m["title"]
    assert m["authors"] == ["张三", "李四"]
    v1 = next(c for c in m["chapters"] if c["title"] == "第一卷")
    assert v1["content"] == "卷首语。" and len(v1["children"]) == 1
    c1 = v1["children"][0]
    assert c1["title"] == "第一章"
    assert "第一段正文\n换行继续" in c1["content"]
    assert "〔3〕" in c1["content"]
    assert c1["notes"] == {"3": "这是第三条注释。"}, c1["notes"]
    assert "\n\n" in c1["content"]          # 空行段落保留
    assert "表格内文字" not in c1["content"]
    assert m["note_count"] == 1
    assert not m["warnings"], m["warnings"]
    print("[OK] DOCX 导入:", p)


def test_endbook_mode():
    """注释形式开关：章末脚注 vs 书末注释（全书统一编号 + 书末注释章节）。"""
    chapters = [
        {"title": "第一章", "content": "正文一〔1〕和〔2〕。",
         "notes": {"1": "第一条注释", "2": "第二条注释"}, "children": []},
        {"title": "第二章", "content": "正文二〔1〕。",
         "notes": {"1": "第二章自己的注释"}, "children": []},
    ]
    p_ch = OUT / "示例章末脚注.epub"
    p_eb = OUT / "示例书末注.epub"
    epub_builder.build_text_epub(p_ch, "注释模式", ["作者"], [], "zh", chapters,
                                 indent_2em=True, split_mode="line", notes_mode="chapter")
    epub_builder.build_text_epub(p_eb, "注释模式", ["作者"], [], "zh", chapters,
                                 indent_2em=True, split_mode="line", notes_mode="endbook")

    with zipfile.ZipFile(p_ch) as z:
        assert "OEBPS/endnotes.xhtml" not in z.namelist()
        ch1 = z.read("OEBPS/chapter_001.xhtml").decode("utf-8", "replace")
        assert 'epub:type="footnotes"' in ch1
        assert ('href="chapter_001.xhtml#note-1-1"' in ch1
                and 'href="chapter_001.xhtml#note-1-2"' in ch1)
    with zipfile.ZipFile(p_eb) as z:
        names = z.namelist()
        assert "OEBPS/endnotes.xhtml" in names
        ch1 = z.read("OEBPS/chapter_001.xhtml").decode("utf-8", "replace")
        ch2 = z.read("OEBPS/chapter_002.xhtml").decode("utf-8", "replace")
        assert 'epub:type="footnotes"' not in ch1          # 无章末注释区
        assert 'href="#note-g1"' in ch1 and 'href="#note-g2"' in ch1
        assert 'href="#note-g3"' in ch2                     # 跨章全局连续编号
        end = z.read("OEBPS/endnotes.xhtml").decode("utf-8", "replace")
        assert end.count('epub:type="endnote"') == 3
        assert "第一条注释" in end and "第二章自己的注释" in end
        assert 'href="#noteref-g1"' in end
        nav = z.read("OEBPS/nav.xhtml").decode("utf-8", "replace")
        assert "注释" in nav and "endnotes.xhtml" in nav    # 目录含书末注释
        opf = z.read("OEBPS/content.opf").decode("utf-8", "replace")
        assert 'idref="endnotes"' in opf.split("<spine")[1]
    print("[OK] 注释形式开关（章末脚注 / 书末注释）:", p_ch, "|", p_eb)


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    test_sanitize()
    test_paragraphs()
    test_text_book()
    test_comic_book()
    test_nested_tree()
    test_notes_footnotes()
    test_multi_creators()
    test_copyright_page()
    test_pubdate_year_only()
    test_import_epub()
    test_import_docx()
    test_layout_modes()
    test_endbook_mode()
    print("\nALL TESTS PASSED")
