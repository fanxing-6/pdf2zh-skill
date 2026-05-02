---
name: pdf2zh-skill
description: Convert English academic papers from PDF into a LaTeX project, translate preserved LaTeX text into Chinese, and compile a Chinese PDF. Use when Codex is asked to process English paper PDFs, DOC2X/Mathpix PDF-to-TeX outputs, or arXiv-style LaTeX projects as a local skill.
---

# PDF LaTeX 中文化

使用本 Skill 将英文论文 PDF 转成 LaTeX 项目，进行分段翻译，并重新编译出尽量保留原始版面的中文 PDF。

当前固定存在两个版本：

- `rebuild`
- `vision-rebuild`

## 运行时基线

默认使用以下本地技术栈：

- PDF 解析：`DOC2X`
- 翻译：用户提供的兼容 `OpenAI Chat Completions` 的 API
- 编译：`lualatex` 优先，必要时回退 `xelatex`

密钥默认通过 `.env` 持久化，不要求每次在命令前临时写环境变量。若 `.env` 未配置翻译 API，Skill 不应擅自假设模型提供商，而应先向用户索取 `base_url`、`api_key` 和 `model`，拿到后再继续后续流程。

视觉重建版本不调用外部多模态 API。它使用脚本先生成视觉对照包，再由 Codex 直接查看页面图片并修改 TeX。

目录职责必须严格区分：

- `scripts/`：仅表示脚本源码目录
- `PDF2ZH_SKILL_HOME`：唯一真实共享运行时根目录
- `PDF2ZH_SKILL_TMPDIR`：任务产出根目录

默认目录约定如下：

- 共享运行时根目录：脚本会在当前用户的主目录下解析出 `pdf2zh-skill` 运行时根目录
- 任务产出根目录：脚本会在当前环境可用的临时目录体系下解析出 `pdf2zh-skill` 任务根目录
- 每次 `run` 在未显式指定 `--output-dir` 时，都必须在 `PDF2ZH_SKILL_TMPDIR` 下创建独立任务子目录，避免互相覆盖

下面的命令示例都假设当前工作目录已经切到本 Skill 根目录。

默认会按以下顺序查找并加载 `.env`：

- `--env-file` 显式指定的文件
- 当前工作目录下的 `.env`
- 本 Skill 根目录下的 `.env`
- `PDF2ZH_SKILL_HOME/.env`

可参考 `.env.example` 创建自己的 `.env`。常用字段如下：

```dotenv
DOC2X_API_KEY=...
PDF2ZH_TRANSLATION_API_KEY=...
PDF2ZH_TRANSLATION_BASE_URL=...
PDF2ZH_TRANSLATION_MODEL=...
```

可先用下面命令查看当前解析后的稳定目录：

```bash
python scripts/pdf2zh_pipeline.py paths
```

如果在 WSL 中运行，脚本会额外打印 Windows 可见路径，便于直接在宿主 Windows 中打开 PDF、日志和 `run_summary.json`。

## 两个版本

### 1. `rebuild`

这是默认版本。它是纯脚本自动流：

1. 用 DOC2X 将 PDF 转成 TeX 项目
2. 切分可翻译片段
3. 用用户提供的翻译 API 并行翻译
4. 自动生成术语表并做一致性复审
5. 做 TeX 级别的版式修补与重建
6. 编译出中文 PDF

适用场景：

- 先跑通全流程
- 追求自动化
- 对版式接近原 PDF 有要求，但允许仍然基于 DOC2X 输出做二次修补

### 2. `vision-rebuild`

这是更强的版本，但它不是纯自动脚本版。它的流程是：

1. 先完整执行 `rebuild` 路径，得到可编译的中文 PDF
2. 额外生成 `vision_pack/`，把原 PDF 与当前中文 PDF 的对应页面渲染成图片
3. Codex 直接查看这些页面图片，比较标题页、图注块、列表块、段间距、图文顺序和局部英文保留情况
4. Codex 修改 `merge_中文.tex`
5. 重新编译并迭代，直到视觉版式更接近原 PDF

视觉能力来自 Codex 自身，不来自外部视觉 API。

适用场景：

- 标题页、作者区、图注区、列表区、页间分隔与原 PDF 差距较大
- 需要尽量接近原 PDF 的视觉版式
- 可以接受由 Codex 参与一轮或多轮视觉对齐

## 主流程

优先使用一条命令的 `run` 入口。它会自动完成以下步骤：

1. 若输入是 PDF，则先调用 DOC2X 转成 TeX 项目
2. 合并主 TeX、屏蔽脆弱 LaTeX 区块、抽取可翻译自然语言片段
3. 先基于全文片段生成 article-level `glossary.json`
4. 使用用户提供的翻译 API 并行翻译片段，并增量写入 `translations.jsonl`
5. 对译文做一次术语一致性复审，输出 `translations_reviewed.jsonl` 与 `consistency_report.json`
6. 重新组装 `merge_中文.tex`
7. 编译出中文 PDF，并写出 `run_summary.json`
8. 若 `--rebuild-mode vision-rebuild`，额外生成 `vision_pack/`

如果用户给的是 arXiv 源码目录或已解压的 TeX 项目，则跳过 PDF 解析，直接从项目目录开始。

如果没有 DOC2X 凭证，可使用 `--method text` 做低保真烟雾测试；但该路径不能稳定保留图、表、公式与排版，因此不应作为正式交付路径。

## 常用命令

推荐的正式入口：

```bash
python scripts/pdf2zh_pipeline.py run --pdf paper.pdf --method doc2x --rebuild-mode rebuild --doc2x-model v2 --workers 50

python scripts/pdf2zh_pipeline.py run --url https://example.com/paper.pdf --method doc2x --rebuild-mode rebuild --doc2x-model v2 --workers 50

python scripts/pdf2zh_pipeline.py run --project relative/or/external/tex-project --rebuild-mode rebuild --workers 50
```

如果需要手工指定任务目录：

```bash
python scripts/pdf2zh_pipeline.py run --pdf paper.pdf --method doc2x --rebuild-mode rebuild --output-dir "${PDF2ZH_SKILL_TMPDIR}/my-task" --workers 50
```

`vision-rebuild` 正式入口：

```bash
python scripts/pdf2zh_pipeline.py run --pdf paper.pdf --method doc2x --rebuild-mode vision-rebuild --vision-pages 1-3 --workers 50

python scripts/pdf2zh_pipeline.py run --project relative/or/external/tex-project --source-pdf relative/or/external/original.pdf --rebuild-mode vision-rebuild --vision-pages 1-3 --workers 50
```

单独生成视觉对照包：

```bash
python scripts/pdf2zh_pipeline.py prepare-vision-pack --source-pdf original.pdf --translated-pdf zh/merge_中文.pdf --tex zh/merge_中文.tex --out work/vision_pack --pages 1-3
```

拆阶段调试时再使用这些子命令：

```bash
python scripts/pdf2zh_pipeline.py convert --pdf paper.pdf --out work/pdf_tex --method doc2x --doc2x-model v2
python scripts/pdf2zh_pipeline.py prepare --project work/pdf_tex --work work/zh
python scripts/pdf2zh_pipeline.py translate --work work/zh --out work/zh/translations.jsonl --workers 50
python scripts/pdf2zh_pipeline.py apply --work work/zh --translations work/zh/translations.jsonl
python scripts/pdf2zh_pipeline.py compile --work work/zh
```

## 翻译与修复规则

翻译固定使用用户提供的兼容 `OpenAI Chat Completions` 的 API。提示词约束是：只翻译论文自然语言，不改 `\section`、`\cite`、`\begin`、`\item`、数学公式、标签、文件名和参考文献键。

脚本会在应用翻译和编译前做几层稳定性修复，包括：

- 保护公式、引用、图表、表格、短命令密集块等脆弱区域
- 修复常见 OCR / LaTeX 兼容字符问题
- 修复未转义文本下划线
- 修复翻译后 `\item` 与正文粘连导致的未定义命令
- 优先用 `lualatex` 编译中文输出

`translate` 默认以 `50` 并发运行，并默认启用更积极的失败重试。若目标接口存在严格速率限制，再按需下调 `--workers` 或 `--max-retries`。

如果论文长度足够且存在重复核心术语，当前流程会自动生成 `glossary.json`，并在翻译后对命中术语的 segment 进行二次一致性修订。短文档或术语重复度不足时，glossary 可能为空，此时一致性复审会自动退化为 no-op，并在 `consistency_report.json` 中写明原因。

## `vision-rebuild` SOP

当用户明确要求尽量贴近原 PDF 的视觉版式时，按下面流程执行：

1. 先用 `run --rebuild-mode vision-rebuild` 跑完整流程。
2. 进入 `vision_pack/`，读取 `manifest.json`。
3. 使用 Codex 自身的视觉能力逐页查看：
   原 PDF 对应页图片
   当前中文 PDF 对应页图片
4. 重点检查以下区域：
   标题页
   作者与机构区
   摘要标题与摘要首段
   图注和图像之间的相对位置
   列表块前后间距
   段间距、空行、页间分隔
   局部英文是否应该保留
5. 不要把中英文长度差异导致的自然分页变化当成视觉重建缺陷。若中文文本变短或变长，从而引起页数变化、图表提前或延后、段落落到相邻页，这属于可接受漂移；视觉重建应优先修复同页内的标题块、作者区、图注块、列表块、对齐方式、空白结构与局部样式错误。
6. 修改 `merge_中文.tex`，不要直接去改原始 `output.tex`。
7. 重新执行 `compile`。
8. 若还有明显视觉偏差，继续看图并迭代。

这条 SOP 的核心是：脚本负责生成可编译起点和视觉对照材料；最终版式对齐由 Codex 直接看图完成。

## WSL 与路径提示

在 WSL 中运行时，默认遵循以下约定：

- 日志里同时输出 Linux 路径和 Windows 可见路径
- `run_summary.json` 中额外写入 `*_windows` 字段，方便宿主 Windows 直接打开结果
- 如果源 PDF 来自已挂载的 Windows 盘符目录，脚本会额外给出对应的 Windows 可见路径

这意味着你在对话中汇报结果时，应优先给用户 Windows 可见路径，而不是只给 WSL 内部路径。

## 资源

- `scripts/pdf2zh_pipeline.py`：CLI 入口
- `scripts/pdf2zh_skill/`：拆分后的实现模块，分别负责路径/公共能力、转换、翻译、LaTeX 处理、视觉重建和 CLI 编排
