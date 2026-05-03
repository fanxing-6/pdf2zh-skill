---
name: pdf2zh-skill
description: Convert English academic papers from PDF or arXiv/LaTeX sources into Chinese PDF outputs. Use when Codex is asked to translate academic PDFs, DOC2X/Mathpix PDF-to-TeX outputs, or arXiv-style LaTeX projects while preserving formulas, citations, figures, and layout as much as practical.
---

# PDF LaTeX 中文化

使用本 Skill 将英文论文 PDF 或 LaTeX 项目转成中文 PDF。流程默认包含：解析/源码获取、分段翻译、术语一致性复审、编译、视觉对照包生成、质量审阅清单生成，然后由 Codex 基于 PDF、TeX、日志和审阅清单进行必要的二次修稿。

## 运行时基线

默认技术栈：

- PDF 解析：`DOC2X`
- arXiv：优先拉取源码包，成功时跳过 PDF 解析
- 翻译：用户提供的兼容 `OpenAI Chat Completions` 的 API
- 编译：`lualatex` 优先，必要时回退 `xelatex`

密钥默认通过 `.env` 持久化。正式运行前应检查有效配置；若缺少翻译 API，Skill 不应假设模型提供商，而应先向用户索取 OpenAI 兼容的 `base_url`、`api_key` 和 `model`。若需要 DOC2X 解析普通 PDF 且缺少 `DOC2X_API_KEY`，应先向用户索取 DOC2X API key。arXiv 源码包可用或用户显式使用 `--project` 时，不要求 DOC2X。

常用 `.env` 字段：

```dotenv
DOC2X_API_KEY=...
PDF2ZH_TRANSLATION_API_KEY=...
PDF2ZH_TRANSLATION_BASE_URL=...
PDF2ZH_TRANSLATION_MODEL=...
```

可先运行配置检查，命令不会打印密钥值：

```bash
python scripts/pdf2zh_pipeline.py check-config
```

缺项时根据提示补 `.env`，或在命令行传入对应参数。

## 输出目录

默认输出根目录为系统临时目录下的 `pdf2zh-skill/` 子目录，可通过 `PDF2ZH_SKILL_TMPDIR` 覆盖。

每次 `run` 都创建独立任务目录：

```text
YYYYMMDD-HHMMSS-<source_slug>-<short_hash>/
```

同一文件多次运行不会互相覆盖。任务目录固定包含：

- `convert/`：PDF 解析或 arXiv 源码获取结果
- `zh/`：内部工作目录
- `vision_pack/`：原 PDF 与中文 PDF 的页面对照图，若缺少源 PDF 则在 `run_summary.json` 中记录跳过原因
- `run_summary.json`：运行摘要、主要产物路径和 Windows 可见路径
- `<原文件名或论文标题>_English.tex`
- `<原文件名或论文标题>_中文.tex`
- `<原文件名或论文标题>_中文.pdf`

内部工作目录保留稳定文件名：

- `merge_English.tex`
- `merge_中文.tex`
- `merge_中文.pdf`
- `segments_English.jsonl`
- `glossary_English.json`
- `translations_中文.jsonl`
- `translations_reviewed_中文.jsonl`
- `consistency_report_中文.json`
- `quality_report_中文.json`
- `quality_report_中文.md`

普通 PDF 的交付文件使用原文件名 stem。arXiv URL 的交付文件优先使用论文标题；标题无法解析时回退到 arXiv ID。

## 主流程

推荐只使用 `run`：

```bash
python scripts/pdf2zh_pipeline.py run --pdf paper.pdf --method doc2x --doc2x-model v2 --workers 50

python scripts/pdf2zh_pipeline.py run --url https://arxiv.org/abs/0000.00000 --workers 50

python scripts/pdf2zh_pipeline.py run --project relative/or/external/tex-project --source-pdf original.pdf --workers 50
```

`run` 会执行：

1. arXiv URL 先探测源码包；普通 PDF 走 DOC2X/Mathpix/text 转换
2. 合并主 TeX，注入中文编译支持，切分可翻译自然语言片段
3. 构建全文术语表 `glossary_English.json`
4. 使用用户提供的翻译 API 并行翻译
5. 执行术语一致性复审
6. 回填生成 `merge_中文.tex`
7. 生成 `quality_report_中文.json` 和 `quality_report_中文.md`
8. 编译 `merge_中文.pdf`
9. 生成 `vision_pack/`
10. 导出原文件名或论文标题后缀的最终交付物

拆阶段调试时再使用子命令：

```bash
python scripts/pdf2zh_pipeline.py check-config
python scripts/pdf2zh_pipeline.py convert --pdf paper.pdf --out work/pdf_tex --method doc2x --doc2x-model v2
python scripts/pdf2zh_pipeline.py prepare --project work/pdf_tex --work work/zh
python scripts/pdf2zh_pipeline.py translate --work work/zh --workers 50
python scripts/pdf2zh_pipeline.py apply --work work/zh --translations work/zh/translations_中文.jsonl
python scripts/pdf2zh_pipeline.py quality-check --work work/zh
python scripts/pdf2zh_pipeline.py compile --work work/zh
python scripts/pdf2zh_pipeline.py prepare-vision-pack --source-pdf original.pdf --translated-pdf work/zh/merge_中文.pdf --tex work/zh/merge_中文.tex --out work/vision_pack --pages 1-3
```

## 模型二次修稿规则

脚本负责生成可编译起点和机器可检测的审阅材料；Codex 负责最终检查和必要修稿。

每次正式交付前，模型应检查：

- `quality_report_中文.md`：提示词泄漏、明显英文残留、坏引用、Markdown 残留、占位符泄漏、异常命令进入正文
- `vision_pack/manifest.json`：原 PDF 与中文 PDF 的页面对照图
- `merge_中文.tex`：需要修复时只改内部工作文件，不改原始 source
- 编译日志：复杂模板和宏包冲突可由模型按日志手工修

不要把中英文长度差异导致的自然分页变化当成缺陷。中文文本变短或变长引起的页数变化、图表提前或延后、段落落到相邻页属于可接受漂移。优先修复同页内标题块、作者区、图注块、列表块、对齐、空白结构和明显文本污染。

## 翻译与修复规则

翻译 API 只翻译论文自然语言，不应改动公式、引用命令、引用 key、标签、文件名和 LaTeX 结构命令。脚本会保护并修复：

- 公式、引用、图表、表格、短命令密集块
- `\Cref{...}`、`\cref{...}`、`\ref{...}`、`\cite{...}` 等引用和 key
- 常见 OCR / LaTeX 兼容字符
- 未转义文本下划线
- `\item` 与正文粘连
- Markdown 加粗、下划线加粗和单反引号残留
- 模型输出原文回声

质量报告只负责指出可检测问题，默认不中断编译。复杂编译错误和版式细节由 Codex 根据日志和视觉对照修复。

## WSL 与路径

在 WSL 中运行时，日志、`run_summary.json` 和 `vision_pack/manifest.json` 必须同时给出 Linux 路径和 Windows 可见路径。

路径规则：

- 挂载的 Windows 盘符路径输出为对应的 Windows 盘符可见路径
- WSL 内部文件系统路径输出为 Windows 资源管理器可打开的 WSL UNC 路径

对用户汇报结果时，优先给 Windows 可见路径。

## 资源

- `scripts/pdf2zh_pipeline.py`：CLI 入口
- `scripts/pdf2zh_skill/`：实现模块
