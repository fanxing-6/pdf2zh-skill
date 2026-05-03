# pdf2zh-skill

`Thinking_with_Visual_Primitives.pdf`:

![Thinking_with_Visual_Primitives before/after](docs/images/thinking_with_visual_primitives_before_after.png)

`arXiv 2604.13016`:

![arXiv 2604.13016 before/after](docs/images/arxiv_2604_13016_before_after.png)

Convert academic PDF papers into Chinese PDF outputs while preserving LaTeX structure as much as possible.

## What it does

- Parse PDF into a TeX project with `DOC2X`
- Segment translatable prose while preserving fragile LaTeX blocks
- Translate with a user-provided OpenAI-compatible chat completions API
- Build a paper-level glossary and run a consistency review pass
- Rebuild `merge_中文.tex` and compile a Chinese PDF
- Optionally generate a vision review pack for manual layout rebuilding

## Default output names

- `merge_English.tex`
- `merge_中文.tex`
- `merge_中文.pdf`
- `segments_English.jsonl`
- `glossary_English.json`
- `translations_中文.jsonl`
- `translations_reviewed_中文.jsonl`
- `consistency_report_中文.json`

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

## Examples

The first example above comes from the DOC2X route.
The second comes from the source-TeX route, where the skill probes arXiv source first and skips DOC2X when the paper source is available.

Raw images are also included:

- `docs/images/thinking_with_visual_primitives_before.png`
- `docs/images/thinking_with_visual_primitives_after.png`
- `docs/images/arxiv_2604_13016_before.png`
- `docs/images/arxiv_2604_13016_after.png`

## Files

- `SKILL.md`: skill contract and operating notes
- `scripts/pdf2zh_pipeline.py`: CLI entrypoint
- `scripts/pdf2zh_skill/`: implementation modules
