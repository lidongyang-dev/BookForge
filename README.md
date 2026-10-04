# BookForge — 自制 Kindle 书籍工作台

> Craft Kindle-ready e-books from TXT/EPUB/DOCX — a local workbench with chapter-tree editing, auto note detection, EPUB/AZW3 export, desktop window & system-tray modes.

自制 Kindle 支持格式（**EPUB / AZW3**）的书籍：把文字做成书、把图片做成漫画。

本地工作台，数据不出本机；桌面窗口 / 系统托盘 / 浏览器三种运行方式任选。



***

## 特性一览



| 能力            | 说明                                                  |
| ------------- | --------------------------------------------------- |
| 文字成书          | 多级目录（卷 → 篇 → 章 → 节，最多 8 层 / 3000 条），每层可填正文          |
| 图片成漫画         | 多图按序成页、拖拽排序、首图自动作封面                                 |
| 三种导入          | TXT（注释感知）、EPUB（还原多级目录与注释）、DOCX（标题样式还原目录、脚注转注释）      |
| 注释系统          | 自动识别〔N〕/\[N]/ 圈号标记；**章末脚注** / **书末注释** 两种模式；跨文件跳转链接 |
| 中英文排版         | 首行缩进 2 字符开关、空行分段 / 回车分段开关，默认值随语言自动设置                |
| 版权页           | 出版社、出版时间（可选，精确到日）、ISBN，自动 © 声明，OPF 元数据同步            |
| 多人著 / 译       | 著者与译者均支持多人（EPUB 规范 `opf:role="aut"/"trl"`）          |
| 便携分发          | 内置便携 Python 与精简版 Calibre，整个文件夹拷走即用                  |
| 桌面窗口          | pywebview 原生窗口（系统 WebView2 内核），双击 start.bat 即开即用，无需浏览器 |
| Material 3 界面 | Google 材质 3 风格，**8 套预设主题色 + 自定义取色**，选择自动记忆          |
| 目录收纳          | 有子章节的条目可点击**折叠 / 展开**（Word 大纲式），状态持久化               |



***

## 快速开始

**唯一便携包，三种启动方式任选**：

| 方式 | 操作 |
|---|---|
| 桌面窗口 | 解压后双击 `创建桌面快捷方式.bat` 在桌面生成 BookForge 图标（自动指向当前解压位置，不写死绝对路径），之后双击图标启动；或直接双击 `start.bat` |
| 系统托盘 | 命令行运行 `python server.py --tray`，托盘图标常驻（左键开网页 / 右键"打开 BookForge / 退出"） |
| 浏览器 | 命令行运行 `python server.py [端口]`，浏览器访问 http://127.0.0.1:8777 |

**命令行**（需 Python 3.8+）：

```
python server.py --desktop   # 桌面窗口模式
python server.py --tray      # 系统托盘模式
python server.py [端口]      # 纯服务模式，浏览器访问 http://127.0.0.1:8777
```

**便携说明**：仓库自带 `runtime\`（便携 Python 3.14.7，含 pywebview / pystray）与 `calibre\`（精简版 Calibre）；`start.bat` 与 `server.py` 优先使用项目内依赖，找不到才回退系统安装。整个文件夹复制到任何 64 位 Windows 电脑即可运行，目标机器**无需预装 Python / Calibre**；复制到新位置后请重新双击 `创建桌面快捷方式.bat` 生成快捷方式（快捷方式不写死路径）。

## 界面预览

![文字成书 · 主界面](screenshots/文字成书-主界面.png)

![图片成漫画 · 界面](screenshots/图片成漫画-界面.png)

## 使用指南

### 文字成书



1. 填写**书名**、**语言**（简体中文 / English / 日本語 / 한국어 / Français / Deutsch）

2. 填写**著者 / 译者**（可多人，输入后回车添加）

3. （可选）在 "版权页" 里填出版社、出版时间（`2026` 或 `2026-10-03`）、ISBN

4. 添加**章节**：`＋ 添加卷 / 章`，或用树内 `+子` / `+后` 构建多级目录

5. 每个条目可填**正文**；留空的条目仅作目录分类层级

6. 选择输出格式：EPUB（新版 Kindle 原生支持）/ AZW3（老款兼容，经 Calibre 转换）

7. 点击 **锻造这本书**，完成后下载

### 目录树编辑



* **多级目录**：卷 → 篇 → 章 → 节，最多 8 层；每条可填正文，空条目只作分类

* **收纳子章节**：有子级的条目左侧有圆形箭头按钮，点击**折叠 / 展开**子章节（Word 大纲式），折叠状态在编辑操作后保持

* **层级调整**：`升层`（变为父级的同级）/ `降层`（归入前一个同级条目之下，子树跟随）/ `↑` `↓`（同层移动）/ `删`（连同子级）

* 目录中间层级（如 "第一卷"）留空时，点目录中该类条目会跳到其后首个正文页

* 页面顶部自动标注层级路径（如 `第一卷 › 第二篇`）

### 从文件导入



| 来源       | 行为                                                                                                                                        |
| -------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| **TXT**  | 可多选连续导入，一篇追加一个章节；自动探测 UTF-8/GBK 编码；**注释感知**：识别〔1〕/\[1]/① 等标记、文末注释表配对、段后注、题解括注保留                                                           |
| **EPUB** | 解析整本：还原多级目录（EPUB3 nav / EPUB2 NCX）、提取正文与注释（footnote/rearnote/endnote、锚点式、跨文件引用均自动还原为〔N〕角标 + 注释表）；回填书名、著者 / 译者、出版社、出版时间、ISBN；**导入后替换当前目录** |
| **DOCX** | 按标题样式（标题 1-9 / Heading 1-9）还原多级目录；正文合并、`<w:br/>` 保留为段内换行、空段落保留；**脚注（footnotes.xml）自动转章末注释**；回填标题与著者；**导入后替换当前目录**                         |

### 注释系统



* **标记格式**：正文中 `〔1〕` / `[1]` / 圈号 `①~⑳` 均可识别，自动统一为 `〔N〕`

* **两种模式**（生成时选择）：


  * **章末脚注**（默认）：每章末尾生成注释区（`epub:type="footnotes"`），正文角标链接到本章注释，带 "返回正文" 链接；多文件时跨文件跳转链接自动带文件名

  * **书末注释**：全书注释统一连续编号，正文角标链接到书末新增的 "注释" 章节（`epub:type="endnote"`）

* **自动识别**：粘贴进正文的文本也自动识别（提交时扫描，有注释区即提取）；**章节标题中的注释标记**（如《论反对日本帝国主义的策略》标题注释）同样视为注释处理

* **注释池**：真实出版物中注释区常集中在一篇末尾，BookForge 采用**篇级注释池**配对 —— 即使注释区与正文不在同一章节也能正确配对渲染

* 注释挂在章节节点上，随节点移动 / 删除正确跟随

### 中英文排版



| 选项        | 中文习惯（默认随 zh）         | 英文习惯（默认随其他语言） |
| --------- | -------------------- | ------------- |
| 首行缩进 2 字符 | 开（`text-indent:2em`） | 关             |
| 段落判定      | 每个回车即新段              | 空行分段（段内换行合并）  |

两个开关均可在界面上手动调整。

### 版权页



* 生成的书固定包含版权页（封面之后、正文之前）：书名、著者 / 译者、出版社、出版时间、ISBN 与自动 © 声明、"本书由 BookForge 制作"

* 出版时间可选：仅年份（`2026`）或精确到日（`2026-10-03`，显示为 "2026 年 10 月 3 日"），留空不显示

* OPF 元数据同步写入 `dc:publisher` / `dc:date`（精确到日带 `opf:event="publication"`）/ ISBN，Calibre 与 Kindle 可读

### 图片成漫画



* 拖拽图片到上传区（JPG/PNG/GIF，可多选），按顺序成页，可拖动排序

* **第一张自动用作封面**

* 单张上限 60 MB，单本最多 500 张

### 界面主题（Material 3）



* 页头下方 "**主题**" 条：8 套预设色（紫 / 蓝 / 绿 / 青 / 橙 / 红 / 粉 / 棕）+ 最右侧**自定义取色器**

* 任意颜色通过算法自动派生整套 Material 3 色板（主色、容器色、表面色、文字色全部联动）

* 选择自动存入浏览器，下次打开保持



***

## 便携分发（runtime /calibre）

BookForge 可整体离线运行：



```
BookForge/
├── runtime\  24 MB  便携 Python 3.14.7 + pywebview（官方 embeddable 包）
├── calibre\ 279 MB  精简版 Calibre（原装 632 MB → 精简 56%）
├── server.py / epub_builder.py / static\ / test_build.py  …
└── start.bat              一键启动（优先 runtime\python.exe）
```

**为什么可以精简**：AZW3 转换（`ebook-convert`）是命令行流程，不依赖 GUI。实测删除

Qt6 WebEngine（191 MB）、onnxruntime、OpenGL 软渲染、ffmpeg、Qt 控件（Widgets/Quick/Qml）、

PDF 库（podofo/poppler）等约 350 MB；**保留** `python-lib.bypy.frozen`（Calibre 核心）、

`Qt6Core/Qt6Gui` + `pyqt6.QtCore/QtGui/sip`（图片处理必需）、ICU、OpenSSL、根目录全部 exe

（worker 子进程使用）。每一步精简均以真实 EPUB→AZW3 转换验证。

**重建依赖**（如需在新机器上重建便携包）：



```
# Python：官方 embeddable 包
curl -L -o runtime\python-embed.zip https://www.python.org/ftp/python/3.14.7/python-3.14.7-embed-amd64.zip
Expand-Archive runtime\python-embed.zip -DestinationPath runtime -Force

# Calibre：复制原装目录后按上述清单删除大件（app\bin 下）
robocopy "C:\Program Files\Calibre2" calibre ebook-convert.exe calibre-debug.exe  # 及根目录其余 exe
robocopy "C:\Program Files\Calibre2\app\bin" calibre\app\bin /E /MT:16
robocopy "C:\Program Files\Calibre2\app\resources" calibre\app\resources /E /MT:16
robocopy "C:\Program Files\Calibre2\app\plugins" calibre\app\plugins /E /MT:16
```

> `server.py`
>
>  查找 Calibre 的顺序：项目内 
>
> `calibre\ebook-convert.exe`
>
>  → 系统常见安装路径。
> 未附带 Calibre 时，EPUB 照常可用，仅 AZW3 不可用。

### 发布包（GitHub Releases）

| 包 | 内容 | 启动方式 |
|---|---|---|
| `BookForge-portable.zip`（唯一便携包） | 完整功能：桌面窗口（pywebview + WebView2）、系统托盘（pystray）、纯浏览器模式；含完整源码、便携 Python 3.14.7、精简版 Calibre | 双击 `创建桌面快捷方式.bat` 生成桌面图标后双击，或 `start.bat`（默认 `--desktop`）；命令行 `python server.py --tray` 托盘、`python server.py` 纯服务 |

一个包即包含全部三种运行模式（桌面窗口 / 系统托盘 / 浏览器），解压即用；目标机缺 .NET Framework 4.8 时桌面窗口自动回退浏览器模式，功能不受影响。



***

## 技术架构

### 目录结构



```
bookforge/
├── server.py            # 本地网页服务（HTTP + 上传解析 + Calibre 转换）
├── epub_builder.py      # EPUB 生成核心（标准库 zipfile 手工构建 EPUB 3 + NCX）
├── static/
│   ├── index.html       # 前端工作台（Material 3，原生 JS，无框架）
│   ├── tree_ops.js      # 目录树逻辑（纯函数，node 可测）
│   └── _backup/ _shots/ # 改版备份 / 自检截图（不入库）
├── runtime/             # 便携 Python + pywebview（不入库）
├── calibre/             # 精简版 Calibre（不入库）
├── test_build.py        # 回归测试（python test_build.py）
├── testdata/            # 回归测试素材
├── output/              # 生成书籍落盘目录（不入库）
└── start.bat            # 一键启动
```

### 生成原理



* **EPUB**：标准库 `zipfile` 手工构建 EPUB 3 包（mimetype /container.xml/content.opf/

  nav.xhtml/toc.ncx），附 NCX 以兼容旧款 Kindle；目录、注释跳转、版权页均为标准 EPUB 语义

* **AZW3**：先产 EPUB，再调用 Calibre `ebook-convert` 转换（KF8 格式）

* **后端实现**：仅用 Python 标准库（http.server / zipfile / urllib / json 等），

  前端原生 JS 无框架

### 前端设计（Material 3）



* CSS 变量承载完整 M3 色板（primary /surface/container /outline 等），

  主题色切换 = 从种子色经 HSL 算法派生 17 个颜色变量写入 `:root`

* 组件：分段式 Tab、Filled/Tonal 按钮、Outlined 输入框、assist-chip、大圆角卡片、M3 阴影

* 目录树独立逻辑文件 `tree_ops.js`（findNodeIn /treePromote/treeDemote 纯函数，

  可脱离 DOM 用 node 测试）

### 校验上限



| 项         | 上限                   |
| --------- | -------------------- |
| 目录深度      | 8 层                  |
| 目录条目数     | 3000 条               |
| 有正文页数     | 2000 页               |
| 单节正文      | 200 万字符              |
| 单条注释      | 5 万字符                |
| 著者 / 译者   | 各最多 20 人，单个姓名 100 字符 |
| 漫画单张 / 单本 | 60 MB / 500 张        |



***

## 开发

### Git 分支



* **main**：稳定版（初始功能：导入 / 树编辑 / 注释 / 版权 / 排版）

* **dev**：开发分支（Material 3 改版、主题色、目录折叠、便携打包等新功能）

### 测试



```
python test_build.py    REM 结构合法性回归（mimetype、spine/manifest、多级目录、
                        REM   章末脚注/书末注链接、跨文件跳转、版权页、导入自举等 15 项）
node test_parse.js      REM 真实 txt 注释解析验证
```

端到端验证：真实 HTTP 请求生成文字书与漫画书，EPUB + AZW3 均产出；

下载、路径穿越防护、404 处理均已验证。

### 前端自检



```
python "<skill-dir>\html\scripts\shot.py" static\index.html
REM 桌面 + 移动截图、console 错误检查、交互按钮检查（输出到 static\_shots\）
```



***

## 常见问题（FAQ）

**Q：把制作好的书传到 Kindle 后没有目录？**

A：Send to Kindle 网页版会把文件经服务端转换链再处理，目录依赖 EPUB 的导航结构。

BookForge 产物包含 EPUB3 nav + NCX 双目录，Calibre 转 AZW3 也保留目录；

若 Kindle 端不显示，请确认发送方式（"文档" vs "书籍" 类型）与 Kindle 固件对目录的支持，

或改用 Kindle 官方 "Send to Kindle" 桌面应用直传文件。

**Q：点击 "锻造" 提示&#x20;**`✗ 网络错误：Failed to fetch`**？**

A：一般原因是本地服务未运行（桌面窗口 / `start.bat` 窗口被关闭）或端口被占用导致新旧进程并存。

确认 8777 端口服务在跑；若改过代码，重启服务并**强制刷新**（桌面窗口模式 Ctrl+F5 或重启窗口；浏览器模式同样 Ctrl+F5）。

**Q：页面改了代码但浏览器里没变化？**

A：静态页面每次请求都从磁盘读取，无需重启服务；浏览器端请 Ctrl+F5 强刷清缓存。

**Q：AZW3 转换失败 / 提示找不到 Calibre？**

A：优先用项目内 `calibre\`（若被删，重新生成见 "便携分发"）；也可安装 Calibre

（默认路径会被自动找到）。EPUB 不依赖 Calibre。

**Q：目录层级升降是什么意思？**

A：`升层`＝节点变为其父级的同级（紧跟原父级之后）；`降层`＝节点归入前一个同级条目

之下成为其子级（子树跟随）。顶层条目不可升层、无前级条目不可降层。

**Q：导出的文件只有部分章节有脚注？**

A：注释配对采用篇级注释池 —— 注释区在篇末集中时，同篇各章正文的角标都会正确配对到

篇末注释区（如 "十四件大事" 页 1\~27 条完整）。确认正文标记为 `〔N〕` 格式且注释表

条目编号完整。



## 卸载与彻底清除

不写注册表、不装系统服务、不留开机启动项。卸载只需两步：

1. 退出 BookForge（关闭桌面窗口 / 托盘右键"退出"）
2. **直接删除 BookForge 文件夹** —— 所有产物都在项目内：`output/`（生成的书稿）、`webview_data/`（GUI 模式的 WebView2 缓存）、`runtime/`、`calibre/`、`__pycache__/` 等，删除文件夹即 100% 清除，系统无任何残留。

***

## 已知限制与后续方向



* 图片原样嵌入（不做压缩 / 缩放），大图会增大体积；后续可加画质 / 体积选项

* 漫画为 reflowable 整页图版；后续可做 Kindle Panel View /fixed-layout

* 可扩展：txt 批量导入增强、MOBI 输出、阅读进度、多语言排版细节、EPUB 固定布局