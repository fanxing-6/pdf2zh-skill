# pdf2zh-skill

Convert academic PDF papers into Chinese PDF outputs while preserving LaTeX structure as much as possible.

## What it does

- Parse PDF into a TeX project with `DOC2X`
- Segment translatable prose while preserving fragile LaTeX blocks
- Translate with a user-provided OpenAI-compatible chat completions API
- Build a paper-level glossary and run a consistency review pass
- Rebuild `merge_translate_zh.tex` and compile a Chinese PDF
- Optionally generate a vision review pack for manual layout rebuilding

## Quick start

Create a `.env` from `.env.example` and fill in your credentials:

```dotenv
DOC2X_API_KEY=...
PDF2ZH_TRANSLATION_API_KEY=...
PDF2ZH_TRANSLATION_BASE_URL=...
PDF2ZH_TRANSLATION_MODEL=...
```

Then run:

```bash
python scripts/pdf2zh_pipeline.py run --pdf paper.pdf --method doc2x --rebuild-mode rebuild
```

For vision-assisted layout rebuilding:

```bash
python scripts/pdf2zh_pipeline.py run --pdf paper.pdf --method doc2x --rebuild-mode vision-rebuild --vision-pages 1-3
```

## Layout modes

- `rebuild`: automatic translation and TeX-level rebuilding
- `vision-rebuild`: generate a visual compare pack and iteratively patch layout by inspecting rendered pages

## Files

- `SKILL.md`: skill contract and operating notes
- `scripts/pdf2zh_pipeline.py`: CLI entrypoint
- `scripts/pdf2zh_skill/`: implementation modules
