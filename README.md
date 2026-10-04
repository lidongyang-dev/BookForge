# BookForge — 自制 Kindle 书籍工作台

把文字做成书、把图片做成漫画，一键产出 **EPUB / AZW3** 两种 Kindle 支持格式。
本地运行，数据不出本机，零第三方 Python 依赖。

## 快速开始

```bat
双击 start.bat
```

或命令行：

```bat
python server.py
```

然后浏览器打开 **http://127.0.0.1:8777**

> AZW3 转换依赖 Calibre（`ebook-convert`）。程序会自动在常见路径查找；
> 若未安装 Calibre，EPUB 照常可用，仅 AZW3 不可用。

## 功能

| 模式 | 说明 |
|---|---|
| 文字成书 | **多级目录**（卷 → 篇 → 章 → 节，最多 8 层，最多 3000 条）、每层可填正文、**条目可提升/降低层级**（升层＝变为父级层级的同级；降层＝归入前一个同级之下，子树跟随）、**注释形式可选**（章末脚注 / 书末注释）、可选封面、EPUB/AZW3 |
| 文字成书 · TXT 导入 | 上传/多选 txt 自动解析：**注释感知**（〔1〕/[1]/① 等标记识别、文末注释表配对、段后注、题解括注保留）、一篇追加一个章节，支持多文件连续导入（如分篇收集的选集 txt） |
| 图片成漫画 | 多图按序成页、拖拽排序、首图自动作封面、EPUB/AZW3 |

- **中英文排版模式**：文字书可分别控制两个排版选项——
  - **首行缩进 2 字符**（中文排版习惯，`text-indent:2em`）
  - **段落判定**：空行分段（英文习惯，段内换行合并）/ 每个回车即新段（中文习惯）
  默认值随所选语言自动设置（中文：缩进开 + 回车换段；其他语言：无缩进 + 空行分段），
  可手动调整。
- **注释形式开关**：生成时可选择
  - **章末脚注**（默认）：每章末尾生成注释区（`epub:type="footnotes"`），正文角标链接到本章注释；
  - **书末注释**：全书注释统一连续编号，正文角标链接到书末新增的"注释"章节
    （`epub:type="endnote"`，带返回正文链接），适合注释集中在篇末/书末的手写书稿。
- **从文件导入**：
  - **TXT**：多选连续导入，一篇追加一个章节，自动探测 UTF-8/GBK 编码。
  - **EPUB**：解析整本已有电子书——自动还原多级目录（EPUB3 nav / EPUB2 NCX），
    提取正文与章末注释（noteref/footnote 配对还原为 BookForge 注释体系），
    **兼容真实出版物多种注释结构**：EPUB3 的 footnote/rearnote/endnote 类型、
    EPUB2 锚点式脚注（`<p id="fn1">` + `<a href="#fn1">`）、
    注释独立成文件（footnotes.xhtml）的跨文件引用——均自动还原为 〔N〕 角标 + 章末注释表；
    回填书名、著者/译者（含 EPUB3 `meta refines` 角色）、出版社、出版时间、ISBN；
    导入后替换当前目录，可直接编辑再锻造。
  - **DOCX**：解析 Word 文档（零第三方依赖，直接读取 OOXML）——按标题样式
    （标题 1-9 / Heading 1-9 及常见 styleId）还原多级目录树，正文段落合并多个
    文本片段、`<w:br/>` 保留为段内换行、空段落保留（供"空行分段"使用），
    脚注（`word/footnotes.xml`）自动转章末注释（〔N〕角标 + 注释表），
    表格内容跳过，回填 `docProps/core.xml` 中的标题与著者；导入后替换当前目录。
- **版权页**：生成的书固定包含版权页（置于封面之后、正文之前）——书名、
  著者/译者、出版社、出版时间、ISBN 与自动 © 声明；出版时间可选，
  支持仅年份（如 `2026`）或精确到日（如 `2026-10-03`，版权页显示为"2026年10月3日"），
  留空则不显示；OPF 元数据同步写入
  `dc:publisher` / `dc:date`（精确到日时带 `opf:event="publication"`）/ ISBN identifier，
  Calibre 与 Kindle 图书信息可读。
- **多人著者/译者**：著者与译者均支持多人（标签式输入，回车逐个添加），
  按 EPUB 规范输出多个 `<dc:creator opf:role="aut">`（著者）/ `opf:role="trl"`（译者），
  Kindle 与 Calibre 可正确识别区分。
- **章末脚注**：正文中已配对的注释标记自动变为可点击角标（EPUB 标准 `epub:type="noteref"`），章末生成注释区（`epub:type="footnotes"`）并带"返回正文"链接；Calibre 转 AZW3 时脚注结构保留。注释挂在章节节点上，随节点移动/删除正确跟随。**直接粘贴的正文同样自动识别注释**（提交时扫描章节文本，有注释区即提取）。
- 目录中间层级（如"第一卷""第二篇"）可留空，仅作分类；点目录中该类条目会跳到其后首个正文页。
- 页面顶部自动标注层级路径（如 `第一卷 › 第二篇`）。
- 支持语言：中文 / English / 日本語 / 한국어 / Français / Deutsch。
- 图片格式：JPG / PNG / GIF（Kindle 兼容格式）。
- txt 编码自动识别：UTF-8 优先，检测到乱码自动按 GBK 重读。

## 项目结构

```
bookforge/
├── server.py            # 本地网页服务（HTTP + 上传解析 + Calibre 转换）
├── epub_builder.py      # EPUB 生成核心（标准库 zipfile 手工构建 EPUB 3 + NCX）
├── static/index.html    # 前端工作台（原生 JS，无框架）
├── test_build.py        # 回归测试（python test_build.py）
├── testdata/            # 回归测试素材
├── output/              # 生成书籍落盘目录
└── start.bat            # 一键启动
```

## 生成原理

- **EPUB**：标准库 `zipfile` 手工构建 EPUB 3 包结构（mimetype / container.xml /
  content.opf / nav.xhtml / toc.ncx），附 NCX 以兼容旧款 Kindle。
- **AZW3**：先产 EPUB，再调用 Calibre `ebook-convert` 转换（KF8 格式）。

## 验证

- `python test_build.py`：结构合法性回归（mimetype 首项且不压缩、spine/manifest
  一致性、文件名清理、段落切分）+ 多级目录 + 章末脚注（noteref 链接、
  footnotes 区、返回链接、未配对标记保留原样、目录不含注释区）。
- `node test_parse.js`：真实 txt 解析验证（《中国社会各阶级的分析》：17 条注释
  全部识别配对、11 段正文、题解括注保留、注释不进正文）。
- 端到端：真实 HTTP 请求生成文字书与漫画书，EPUB + AZW3 均产出，
  下载、路径穿越防护、404 处理均已验证。

## 已知限制与后续方向

- 图片原样嵌入（不做压缩/缩放），大图会增大体积；后续可加画质/体积选项。
- 漫画为 reflowable 整页图版；后续可做 Kindle Panel View / fixed-layout。
- 可扩展：txt 批量导入、MOBI 输出、阅读进度、多语言排版细节。
