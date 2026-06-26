from __future__ import annotations

from .common import *
from .conversion import *
from .latex_ops import *
from .translate import *
from .vision import *

ENGLISH_MERGED_BASENAME = "merge_English"
CHINESE_MERGED_BASENAME = "merge_中文"
BILINGUAL_MERGED_BASENAME = "merge_中英双语"
BILINGUAL_COLOR_NAME = "pdf2zhChineseGreen"
INLINE_BILINGUAL_ARG_COMMANDS = {"caption", "title"}
ENGLISH_SEGMENTS_NAME = "segments_English.jsonl"
ENGLISH_DEBUG_SEGMENTS_NAME = "debug_segments_English.html"
ENGLISH_GLOSSARY_NAME = "glossary_English.json"
ENGLISH_GLOSSARY_CANDIDATES_NAME = "glossary_candidates_English.json"
CHINESE_TRANSLATIONS_NAME = "translations_中文.jsonl"
CHINESE_REVIEWED_TRANSLATIONS_NAME = "translations_reviewed_中文.jsonl"
CHINESE_CONSISTENCY_REPORT_NAME = "consistency_report_中文.json"
CHINESE_QUALITY_REPORT_JSON_NAME = "quality_report_中文.json"
CHINESE_QUALITY_REPORT_MD_NAME = "quality_report_中文.md"

BLOCKING_QUALITY_KINDS = {
    "prompt_leak",
    "bad_reference_key",
    "placeholder_leak",
    "double_escaped_reference",
    "malformed_reference_command",
    "malformed_reference_key",
    "latex_section_inside_prose",
    "missing_list_item",
    "latex_control_word_split",
}


def safe_output_artifact_base(name: str) -> str:
    cleaned = re.sub(r"\s+", " ", name)
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1F]+', "_", cleaned).strip().rstrip(".")
    if len(cleaned) > 120:
        cleaned = cleaned[:120].rstrip(" ._-")
    return cleaned or "output"


def persist_source_pdf(pdf: Path, output_dir: Path) -> Path:
    if not pdf.is_file():
        die(f"source PDF not found: {pdf}")
    source_dir = output_dir / "source"
    source_dir.mkdir(parents=True, exist_ok=True)
    safe_name = safe_output_artifact_base(pdf.name)
    if not safe_name.lower().endswith(".pdf"):
        safe_name = f"{safe_name}.pdf"
    target = source_dir / safe_name
    try:
        same_file = target.exists() and pdf.samefile(target)
    except OSError:
        same_file = False
    if not same_file:
        shutil.copy2(pdf, target)
    return target.resolve()


def latex_to_plain_filename(value: str) -> str:
    text = value.replace("\\\\", " ")
    for _ in range(4):
        text = re.sub(r"\\[A-Za-z]+\*?(?:\[[^\]]*\])?\{([^{}]*)\}", r"\1", text)
    text = re.sub(r"\$([^$]*)\$", r"\1", text)
    text = re.sub(r"\\[A-Za-z]+\*?", " ", text)
    text = re.sub(r"[{}$]", " ", text)
    return compact_whitespace(text)


def first_latex_command_argument(text: str, command: str) -> str | None:
    pattern = re.compile(rf"\\{re.escape(command)}\s*(?:\[[^\]]*\])?\{{", re.S)
    match = pattern.search(text)
    if not match:
        return None
    start = match.end()
    depth = 1
    index = start
    while index < len(text):
        char = text[index]
        if char == "\\":
            index += 2
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start:index]
        index += 1
    return None


def title_from_project(project: Path) -> str | None:
    try:
        main = find_main_tex(project)
        merged = merge_tex(project, main)
    except Exception:
        tex_files = sorted(project.rglob("*.tex"))
        if not tex_files:
            return None
        merged = tex_files[0].read_text(encoding="utf-8", errors="ignore")
    raw_title = first_latex_command_argument(merged, "title")
    if not raw_title:
        return None
    title = latex_to_plain_filename(raw_title)
    return title or None


def output_artifact_base_for_run(
    *,
    source: str,
    project: Path,
    source_pdf: Path | None = None,
) -> str:
    if re.match(r"^https?://", source) and arxiv_id_from_url(source):
        title = title_from_project(project)
        if title:
            return safe_output_artifact_base(title)
        arxiv_id = arxiv_id_from_url(source)
        if arxiv_id:
            return safe_output_artifact_base(arxiv_id)
    if source_pdf is not None and source_pdf.is_file():
        return safe_output_artifact_base(source_pdf.stem)
    if re.match(r"^https?://", source):
        parsed = urlparse(source)
        candidate = Path(parsed.path).stem or Path(parsed.path).name
    else:
        candidate = Path(source).stem or Path(source).name
    if not candidate or candidate in {"project", "source", "output", "run"}:
        candidate = project.stem or project.name
    return safe_output_artifact_base(candidate)


def export_named_outputs(output_dir: Path, work: Path, artifact_base: str) -> dict[str, Path]:
    exports = {
        "english_tex": output_dir / f"{artifact_base}_English.tex",
        "tex": output_dir / f"{artifact_base}_中文.tex",
        "pdf": output_dir / f"{artifact_base}_中文.pdf",
        "bilingual_tex": output_dir / f"{artifact_base}_中英双语.tex",
        "bilingual_pdf": output_dir / f"{artifact_base}_中英双语.pdf",
    }
    shutil.copy2(work / f"{ENGLISH_MERGED_BASENAME}.tex", exports["english_tex"])
    shutil.copy2(work / f"{CHINESE_MERGED_BASENAME}.tex", exports["tex"])
    shutil.copy2(work / f"{CHINESE_MERGED_BASENAME}.pdf", exports["pdf"])
    shutil.copy2(work / f"{BILINGUAL_MERGED_BASENAME}.tex", exports["bilingual_tex"])
    shutil.copy2(work / f"{BILINGUAL_MERGED_BASENAME}.pdf", exports["bilingual_pdf"])
    return exports


def extract_env_file_arg(argv: list[str] | None) -> str | None:
    if not argv:
        return None
    for index, token in enumerate(argv):
        if token == "--env-file" and index + 1 < len(argv):
            return argv[index + 1]
        if token.startswith("--env-file="):
            return token.split("=", 1)[1]
    return None

def cmd_convert(args: argparse.Namespace) -> None:
    out = Path(args.out).resolve()
    pdf = Path(args.pdf).resolve() if args.pdf else None
    if args.url and pdf is None:
        arxiv_project = download_arxiv_source_project(args.url, out / "arxiv_source")
        if arxiv_project is not None:
            project, _pdf = arxiv_project
            print(project)
            return
        pdf = download_remote_pdf(args.url, out / "remote_source")
    if pdf is None or not pdf.is_file():
        die("--pdf is required and must point to an existing file, or provide --url")

    if args.method == "doc2x":
        convert_doc2x(pdf, out, args.api_key, args.doc2x_model)
    elif args.method == "mathpix":
        convert_mathpix(pdf, out, args.mathpix_app_id, args.mathpix_app_key)
    else:
        convert_text_fallback(pdf, out)

def cmd_prepare(args: argparse.Namespace) -> None:
    project = Path(args.project).resolve()
    work = Path(args.work).resolve()
    if not project.is_dir():
        die(f"project folder not found: {project}")
    if work.exists() and args.force:
        shutil.rmtree(work)
    work.mkdir(parents=True, exist_ok=True)
    source = work / "source"
    if source.exists():
        shutil.rmtree(source)
    shutil.copytree(project, source)
    for item in source.iterdir():
        if item.name.startswith("merge"):
            continue
        target = work / item.name
        if item.is_dir():
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(item, target)
        elif item.suffix.lower() not in {".tex"}:
            shutil.copy2(item, target)

    main = find_main_tex(source)
    source_bbl = main.with_suffix(".bbl")
    if source_bbl.is_file():
        shutil.copy2(source_bbl, work / f"{ENGLISH_MERGED_BASENAME}.bbl")
        shutil.copy2(source_bbl, work / f"{CHINESE_MERGED_BASENAME}.bbl")
        shutil.copy2(source_bbl, work / f"{BILINGUAL_MERGED_BASENAME}.bbl")
    merged = sanitize_latex_source(inject_chinese_support(merge_tex(source, main)))
    (work / f"{ENGLISH_MERGED_BASENAME}.tex").write_text(merged, encoding="utf-8")
    nodes = split_nodes(merged)
    state = {
        "source_project": str(project),
        "work": str(work),
        "main_tex": str(main.relative_to(source)),
        "nodes": [asdict(node) for node in nodes],
    }
    (work / "pipeline_state.json").write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    write_debug_html(work / ENGLISH_DEBUG_SEGMENTS_NAME, nodes)
    segments = [{"id": node.segment_id, "text": node.text} for node in nodes if node.kind == TRANSLATE]
    write_jsonl(work / ENGLISH_SEGMENTS_NAME, segments)
    print(f"main={main}")
    print(f"segments={len(segments)}")
    print(work)

def write_debug_html(path: Path, nodes: list[Node]) -> None:
    rows = ["<html><meta charset='utf-8'><body>"]
    for node in nodes:
        color = "#111" if node.kind == TRANSLATE else "#a33"
        label = node.segment_id or node.kind
        rows.append(f"<pre style='white-space:pre-wrap;color:{color};border-bottom:1px solid #ddd;padding:8px'>[{label}]\n{html.escape(node.text)}</pre>")
    rows.append("</body></html>")
    path.write_text("\n".join(rows), encoding="utf-8")

def cmd_prompts(args: argparse.Namespace) -> None:
    work = Path(args.work).resolve()
    state_path = work / "pipeline_state.json"
    if not state_path.is_file():
        die(f"missing state file: {state_path}")
    state = json.loads(state_path.read_text(encoding="utf-8"))
    glossary = f"\nAdditional glossary or style rule: {args.requirement.strip()}" if args.requirement else ""
    rows = []
    for node in state["nodes"]:
        if node["kind"] != TRANSLATE:
            continue
        rows.append(
            {
                "id": node["segment_id"],
                "system": "You are a professional academic paper translator.",
                "prompt": (
                    "Translate the following English academic LaTeX segment into Chinese. "
                    "Do not modify LaTeX commands, citation keys, labels, equations, begin/end environments, file names, or braces. "
                    "Keep reference and citation commands byte-for-byte unchanged, including \\Cref{...}, \\cref{...}, \\ref{...}, \\eqref{...}, \\pageref{...}, \\nameref{...}, \\cite{...}, \\citep{...}, \\citet{...}; never escape underscores inside their braces. "
                    "Do not use Markdown syntax such as **bold**, __bold__, `code`, headings, or bullet lists. "
                    "Return only the translated segment."
                    f"{glossary}\n\n{node['text']}"
                ),
                "original": node["text"],
            }
        )
    write_jsonl(Path(args.out).resolve(), rows)
    print(f"wrote {len(rows)} prompts to {args.out}")

def cmd_glossary(args: argparse.Namespace) -> None:
    work = Path(args.work).resolve()
    segments_path = work / ENGLISH_SEGMENTS_NAME
    if not segments_path.is_file():
        die(f"missing segments file: {segments_path}; run prepare first")

    api_key, base_url, model = resolve_translation_settings(
        api_key=args.api_key,
        base_url=args.base_url,
        model=args.model,
    )

    out = Path(args.out).resolve() if args.out else work / ENGLISH_GLOSSARY_NAME
    candidates_path = work / ENGLISH_GLOSSARY_CANDIDATES_NAME
    segments = load_jsonl(segments_path)
    candidates = collect_glossary_candidates(segments, max_candidates=args.max_candidates)
    candidates_path.write_text(json.dumps({"candidates": candidates}, ensure_ascii=False, indent=2), encoding="utf-8")

    if not candidates:
        out.write_text(json.dumps({"terms": []}, ensure_ascii=False, indent=2), encoding="utf-8")
        print(out)
        return

    log(f"Glossary: building article-level glossary from {len(candidates)} candidates")
    requirement_block = (
        "User-specific terminology or style requirement:\n"
        f"{args.requirement.strip()}\n\n"
        if args.requirement.strip()
        else ""
    )
    messages = [
        {
            "role": "system",
            "content": "You are a terminology editor for Chinese translation of academic papers.",
        },
        {
            "role": "user",
            "content": (
                "Below is a candidate terminology list extracted from one English academic paper.\n"
                "Select the paper-specific terms and abbreviations that must stay globally consistent in the Chinese translation.\n"
                "Return JSON only in the shape {\"terms\": [{\"source\": str, \"translation\": str, \"type\": \"term|abbreviation\", \"aliases\": [str], \"note\": str}]}.\n"
                "Rules:\n"
                "- Keep only terms worth enforcing across the whole article.\n"
                "- Exclude generic academic filler such as 'this paper' or 'related work'.\n"
                "- Prefer concise and idiomatic Chinese translations.\n"
                "- If singular/plural or close surface variants should share one translation, put the main form in source and the others in aliases.\n"
                f"- Keep at most {args.max_terms} items.\n"
                f"{requirement_block}"
                "Candidate data:\n"
                f"{json.dumps(candidates, ensure_ascii=False, indent=2)}"
            ),
        },
    ]
    payload = call_chat_json(
        api_key=api_key,
        base_url=base_url,
        model=model,
        messages=messages,
        timeout=args.timeout_seconds,
        max_retries=args.max_retries,
    )
    terms = normalize_glossary_terms(payload, max_terms=args.max_terms)
    out.write_text(json.dumps({"terms": terms}, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"Glossary: wrote {len(terms)} normalized terms")
    print(out)

def cmd_translate(args: argparse.Namespace) -> None:
    work = Path(args.work).resolve()
    segments_path = work / ENGLISH_SEGMENTS_NAME
    if not segments_path.is_file():
        die(f"missing segments file: {segments_path}; run prepare first")

    api_key, base_url, model = resolve_translation_settings(
        api_key=args.api_key,
        base_url=args.base_url,
        model=args.model,
    )

    out = Path(args.out).resolve() if args.out else work / CHINESE_TRANSLATIONS_NAME
    segments = load_jsonl(segments_path)
    glossary_terms = load_glossary_terms(Path(args.glossary).resolve()) if args.glossary else load_glossary_terms(work / ENGLISH_GLOSSARY_NAME)
    glossary_text = format_glossary_for_prompt(glossary_terms)
    if glossary_terms:
        log(f"Translate: loaded {len(glossary_terms)} glossary terms")
    existing: dict[str, dict] = {}
    if out.is_file() and not args.force:
        for row in load_jsonl(out):
            segment_id = row.get("id")
            translation = row.get("translation")
            if segment_id and translation:
                existing[segment_id] = row

    by_id: dict[str, dict] = dict(existing)
    translated_now = 0
    skipped = 0
    suspicious = 0
    pending = []
    for index, segment in enumerate(segments, 1):
        if segment["id"] in existing and not args.force:
            skipped += 1
            continue
        if args.limit and len(pending) >= args.limit:
            continue
        pending.append((index, segment))

    def ordered_rows() -> list[dict]:
        return [by_id[segment["id"]] for segment in segments if segment["id"] in by_id]

    def translate_one(item: tuple[int, dict]) -> tuple[str, str, bool, int]:
        index, segment = item
        segment_id = segment["id"]
        original = segment["text"]
        log(f"Translate: {segment_id} ({index}/{len(segments)}, {len(original)} chars)")
        translated, attempts, looks_untranslated = translate_with_retries(
            original,
            api_key=api_key,
            base_url=base_url,
            model=model,
            requirement=args.requirement,
            glossary_text=glossary_text,
            timeout=args.timeout_seconds,
            max_retries=args.max_retries,
            retry_untranslated=args.retry_untranslated,
        )
        return segment_id, translated, looks_untranslated, attempts

    if pending and args.workers > 1:
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = [executor.submit(translate_one, item) for item in pending]
            for future in as_completed(futures):
                segment_id, translated, looks_untranslated, attempts = future.result()
                if looks_untranslated:
                    suspicious += 1
                    log(f"Translate: warning {segment_id} still looks mostly untranslated")
                by_id[segment_id] = {
                    "id": segment_id,
                    "translation": translated,
                    "model": model,
                    "attempts": attempts,
                }
                translated_now += 1
                write_jsonl(out, ordered_rows())
    else:
        for item in pending:
            segment_id, translated, looks_untranslated, attempts = translate_one(item)
            if looks_untranslated:
                suspicious += 1
                log(f"Translate: warning {segment_id} still looks mostly untranslated")
            by_id[segment_id] = {
                "id": segment_id,
                "translation": translated,
                "model": model,
                "attempts": attempts,
            }
            translated_now += 1
            write_jsonl(out, ordered_rows())

    rows = ordered_rows()
    write_jsonl(out, rows)
    print(f"wrote {len(rows)} translations to {out}")
    print(f"translated_now={translated_now} skipped={skipped} suspicious={suspicious}")

def cmd_review_consistency(args: argparse.Namespace) -> None:
    work = Path(args.work).resolve()
    segments_path = work / ENGLISH_SEGMENTS_NAME
    if not segments_path.is_file():
        die(f"missing segments file: {segments_path}; run prepare first")

    api_key, base_url, model = resolve_translation_settings(
        api_key=args.api_key,
        base_url=args.base_url,
        model=args.model,
    )

    translations_path = Path(args.translations).resolve()
    if not translations_path.is_file():
        die(f"missing translations file: {translations_path}")

    out = Path(args.out).resolve() if args.out else work / CHINESE_REVIEWED_TRANSLATIONS_NAME
    report_path = Path(args.report).resolve() if args.report else work / CHINESE_CONSISTENCY_REPORT_NAME

    segments = load_jsonl(segments_path)
    original_rows = load_jsonl(translations_path)
    glossary_path = Path(args.glossary).resolve() if args.glossary else work / ENGLISH_GLOSSARY_NAME
    glossary_terms = load_glossary_terms(glossary_path)
    if not glossary_terms:
        write_jsonl(out, original_rows)
        report = {
            "glossary_terms": 0,
            "segments_total": len(segments),
            "segments_with_term_matches": 0,
            "segments_flagged": 0,
            "segments_changed": 0,
            "issues_before": 0,
            "issues_after": 0,
            "items": [],
            "note": f"no review performed because glossary is empty: {glossary_path}",
        }
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        log(f"Consistency: skipped review because glossary is empty at {glossary_path}")
        print(out)
        print(report_path)
        return

    translations_by_id = {row["id"]: dict(row) for row in original_rows if row.get("id")}

    review_items = []
    total_issues_before = 0
    segments_with_term_matches = 0
    for segment in segments:
        segment_id = segment["id"]
        if segment_id not in translations_by_id:
            continue
        matched_terms = glossary_terms_for_segment(segment["text"], glossary_terms)
        if matched_terms:
            segments_with_term_matches += 1
        missing_terms = missing_preferred_terms(translations_by_id[segment_id]["translation"], matched_terms)
        if missing_terms:
            total_issues_before += len(missing_terms)
            review_items.append(
                {
                    "id": segment_id,
                    "original": segment["text"],
                    "current_translation": translations_by_id[segment_id]["translation"],
                    "matched_terms": matched_terms,
                    "missing_terms": missing_terms,
                }
            )

    log(
        "Consistency: "
        f"{len(review_items)} segments flagged, {total_issues_before} preferred-term issues, "
        f"{segments_with_term_matches} segments matched glossary terms"
    )

    report_items: list[dict] = []
    changed = 0
    total_issues_after = 0

    def review_one(item: dict) -> tuple[str, dict, dict]:
        current = item["current_translation"]
        after_missing = item["missing_terms"]
        attempts = 0
        while after_missing and attempts < 2:
            extra_rule = ""
            if attempts:
                extra_rule = (
                    "The previous consistency revision still missed these required preferred translations: "
                    + ", ".join(f"{term['source']} -> {term['translation']}" for term in after_missing)
                    + ". Use them explicitly if the English source term appears."
                )
            revised = revise_translation_for_consistency(
                original=item["original"],
                current_translation=current,
                matched_terms=item["matched_terms"],
                api_key=api_key,
                base_url=base_url,
                model=model,
                requirement="\n".join(part for part in [args.requirement.strip(), extra_rule] if part),
                timeout=args.timeout_seconds,
                max_retries=args.max_retries,
            )
            current = fix_translation(revised, item["original"])
            after_missing = missing_preferred_terms(current, item["matched_terms"])
            attempts += 1
        report_item = {
            "id": item["id"],
            "matched_terms": [{"source": term["source"], "translation": term["translation"]} for term in item["matched_terms"]],
            "missing_before": [{"source": term["source"], "translation": term["translation"]} for term in item["missing_terms"]],
            "missing_after": [{"source": term["source"], "translation": term["translation"]} for term in after_missing],
            "changed": current != item["current_translation"],
            "review_attempts": attempts,
        }
        return item["id"], {
            "id": item["id"],
            "translation": current,
            "model": model,
            "reviewed_for_consistency": True,
        }, report_item

    if review_items and args.workers > 1:
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = [executor.submit(review_one, item) for item in review_items]
            for future in as_completed(futures):
                segment_id, row, report_item = future.result()
                if report_item["changed"]:
                    changed += 1
                total_issues_after += len(report_item["missing_after"])
                report_items.append(report_item)
                existing = translations_by_id.get(segment_id, {})
                existing.update(row)
                translations_by_id[segment_id] = existing
    else:
        for item in review_items:
            segment_id, row, report_item = review_one(item)
            if report_item["changed"]:
                changed += 1
            total_issues_after += len(report_item["missing_after"])
            report_items.append(report_item)
            existing = translations_by_id.get(segment_id, {})
            existing.update(row)
            translations_by_id[segment_id] = existing

    ordered_rows = [translations_by_id[segment["id"]] for segment in segments if segment["id"] in translations_by_id]
    write_jsonl(out, ordered_rows)
    report = {
        "glossary_terms": len(glossary_terms),
        "segments_total": len(segments),
        "segments_with_term_matches": segments_with_term_matches,
        "segments_flagged": len(review_items),
        "segments_changed": changed,
        "issues_before": total_issues_before,
        "issues_after": total_issues_after,
        "items": sorted(report_items, key=lambda item: item["id"]),
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(out)
    print(report_path)

def cmd_prepare_vision_pack(args: argparse.Namespace) -> None:
    source_pdf = Path(args.source_pdf).expanduser().resolve()
    translated_pdf = Path(args.translated_pdf).expanduser().resolve()
    if not source_pdf.is_file():
        die(f"source PDF not found: {source_pdf}")
    if not translated_pdf.is_file():
        die(f"translated PDF not found: {translated_pdf}")
    tex_path = Path(args.tex).expanduser().resolve() if args.tex else None
    pack_dir = prepare_vision_review_pack(
        source_pdf=source_pdf,
        translated_pdf=translated_pdf,
        out_dir=Path(args.out).expanduser().resolve(),
        pages_spec=args.pages,
        tex_path=tex_path,
    )
    log_path_hint("Vision review pack", pack_dir)
    log_path_hint("Vision review manifest", pack_dir / "manifest.json")
    print(pack_dir)


def localize_preserved_text_for_chinese(text: str) -> str:
    """Localize small prose fragments that were preserved with LaTeX refs."""
    if not text:
        return text
    text = re.sub(r"\bFigures~", "图~", text)
    text = re.sub(r"\bFigure~", "图~", text)
    text = re.sub(r"\bTables~", "表~", text)
    text = re.sub(r"\bTable~", "表~", text)
    text = re.sub(r"\bAppendices~", "附录~", text)
    text = re.sub(r"\bAppendix~", "附录~", text)
    text = re.sub(r",\s*(\\cite(?:t|p)?\{[^{}]+\}),\s*and\s+(\\cite(?:t|p)?\{[^{}]+\})", r"、\1 和 \2", text)
    text = re.sub(r",\s*and\s+(\\cite(?:t|p)?\{[^{}]+\})", r" 和 \1", text)
    text = re.sub(r"^\s*,\s*(\\cite(?:t|p)?\{[^{}]+\})", r"、\1", text)
    text = re.sub(r"(\\ref\{[^{}]+\}),\s*and\s+(~?\\ref\{)", r"\1、\2", text)
    text = re.sub(r"(\\ref\{[^{}]+\}),\s+(~?\\ref\{)", r"\1、\2", text)
    text = re.sub(r"(\\ref\{[^{}]+\})\s+and\s+(\\ref\{)", r"\1 和 \2", text)
    text = re.sub(r",\s*and\s+(?=(?:~?\\ref\{|[A-Z][A-Za-z0-9-]*~\\citep\{|[A-Z][A-Za-z0-9-]*))", "、", text)
    text = re.sub(r"^\s*,\s*(?=[A-Z][A-Za-z0-9-]*(?:~\\citep\{|\\footnote|\b))", "、", text)
    text = text.replace(", or delta tuning", "，以及 delta tuning")
    text = text.replace(" and token merging", "和 token merging")
    text = text.replace(" for more details on datasets.", "了解数据集的更多细节。")
    text = text.replace(" for detailed information.", "，以了解详细信息。")
    text = text.replace(" and 附录~", "另见附录~")
    return text


def with_abstract_name(text: str, title: str) -> str:
    if r"\begin{abstract}" not in text:
        return text
    marker = "% pdf2zh-skill abstract name"
    if marker in text:
        return text
    insertion = (
        marker
        + "\n"
        + rf"\providecommand{{\abstractname}}{{{title}}}"
        + "\n"
        + rf"\renewcommand{{\abstractname}}{{{title}}}"
        + "\n"
    )
    begin_doc = re.search(r"\\begin\{document\}", text)
    if begin_doc:
        return text[: begin_doc.start()] + insertion + text[begin_doc.start() :]
    return insertion + text


def localize_support_files_for_chinese(work: Path) -> None:
    for style_path in work.glob("*.sty"):
        try:
            text = style_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        updated = text.replace(r"\centerline{\large\bf Abstract}", r"\centerline{\large\bf 摘要}")
        if updated != text:
            style_path.write_text(updated, encoding="utf-8")


def cmd_apply(args: argparse.Namespace) -> None:
    work = Path(args.work).resolve()
    state_path = work / "pipeline_state.json"
    if not state_path.is_file():
        die(f"missing state file: {state_path}")
    state = json.loads(state_path.read_text(encoding="utf-8"))
    translations = {row["id"]: row.get("translation", "") for row in load_jsonl(Path(args.translations).resolve())}
    if not translations:
        die("translation JSONL is empty")
    localize_support_files_for_chinese(work)

    pieces: list[str] = []
    missing: list[str] = []
    reverted: list[str] = []
    for node in state["nodes"]:
        if node["kind"] == PRESERVE:
            pieces.append(localize_preserved_text_for_chinese(node["text"]))
            continue
        segment_id = node["segment_id"]
        translated = translations.get(segment_id)
        if translated is None:
            missing.append(segment_id)
            translated = node["text"]
        fixed = fix_translation(translated, node["text"])
        if fixed == node["text"] and translated != node["text"]:
            reverted.append(segment_id)
        pieces.append(fixed)
    if missing:
        print(f"warning: missing translations for {len(missing)} segments: {', '.join(missing[:10])}", file=sys.stderr)
    if reverted:
        print(f"warning: reverted {len(reverted)} risky translations: {', '.join(reverted[:10])}", file=sys.stderr)

    out = work / f"{CHINESE_MERGED_BASENAME}.tex"
    final_text = "".join(pieces)
    final_text = normalize_frontmatter_content(final_text)
    final_text = normalize_frontmatter_layout(final_text)
    final_text = with_abstract_name(final_text, "摘要")
    final_text = with_bibliography_input(final_text, f"{CHINESE_MERGED_BASENAME}.bbl")
    out.write_text(sanitize_latex_source(final_text), encoding="utf-8")
    print(out)


STRUCTURAL_BILINGUAL_COMMANDS = {
    "title",
    "section",
    "subsection",
    "subsubsection",
    "paragraph",
    "subparagraph",
}


def latex_command_at(text: str, start: int, allowed: set[str]) -> dict | None:
    pattern = re.compile(
        r"\\(?P<name>[A-Za-z@]+)(?P<star>\*)?(?P<options>(?:\s*\[[^\]]*\])*)\s*\{",
        re.S,
    )
    match = pattern.match(text, start)
    if not match or match.group("name") not in allowed:
        return None

    index = match.end()
    depth = 1
    while index < len(text):
        char = text[index]
        if char == "\\":
            index += 2
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return {
                    "name": match.group("name"),
                    "start": match.start(),
                    "arg_start": match.end(),
                    "arg_end": index,
                    "end": index + 1,
                    "open": text[match.start() : match.end()],
                    "arg": text[match.end() : index],
                }
        index += 1
    return None


def first_latex_command(text: str, allowed: set[str]) -> dict | None:
    pattern = re.compile(r"\\(?:%s)(?:\*)?(?:\s*\[[^\]]*\])*\s*\{" % "|".join(sorted(allowed)))
    for match in pattern.finditer(text):
        command = latex_command_at(text, match.start(), allowed)
        if command:
            return command
    return None


def strip_label_commands(text: str) -> str:
    return re.sub(r"\\label\s*\{[^{}]*\}", "", text)


def normalize_bilingual_inline_latex(text: str) -> str:
    color_names = {
        "蓝色": "blue",
        "红色": "red",
        "绿色": "green",
        "灰色": "gray",
        "黑色": "black",
        "白色": "white",
        "黄色": "yellow",
    }

    def color_repl(match: re.Match) -> str:
        zh_color = match.group(1)
        body = match.group(2).strip()
        color = color_names[zh_color]
        if body.lower() in {"blue", "red", "green", "gray", "grey", "black", "white", "yellow"}:
            body = zh_color
        return rf"\textcolor{{{color}}}{{{body}}}"

    text = re.sub(r"\\textcolor\{(蓝色|红色|绿色|灰色|黑色|白色|黄色)\}\{([^{}]*)\}", color_repl, text)
    text = re.sub(r"\\hl\{([^{}]*)\}", r"\\textbf{\1}", text)
    return compact_whitespace(text)


def green_inline(text: str) -> str:
    content = normalize_bilingual_inline_latex(strip_label_commands(text).strip())
    if not content:
        return ""
    return rf"\textcolor{{{BILINGUAL_COLOR_NAME}}}{{{content}}}"


def green_block(text: str) -> str:
    content = strip_label_commands(text).strip()
    if not content:
        return ""
    return f"\n\n\\begingroup\\color{{{BILINGUAL_COLOR_NAME}}}\n{content}\n\\endgroup\n\n"


def green_sentence(text: str) -> str:
    content = normalize_bilingual_inline_latex(strip_label_commands(text).strip())
    if not content:
        return ""
    return rf"{{\color{{{BILINGUAL_COLOR_NAME}}} {content}}}"


def strip_leading_sentence_continuation(text: str) -> str:
    # TeX segmentation often leaves ". Next sentence" or ", which ..." at the
    # start of a node after citation-heavy text. For bilingual display, avoid
    # rendering those marks as standalone sentence lines.
    return re.sub(r"^\s*(?:[.;:。；：]\s+|[,，]\s*)+", "", text)


def strip_bilingual_list_option_noise(text: str) -> str:
    return re.sub(
        r"^\s*\[[^\]\n]*(?:label|topsep|itemsep|leftmargin)[^\]\n]*\]\s*(?=\\item\b)",
        "",
        text,
        count=1,
    )


def leading_sentence_mark(text: str) -> str | None:
    match = re.match(r"^\s*([.!?;:。！？；：])(?=\s|[}\)]|$)", text)
    return match.group(1) if match else None


def strip_leading_sentence_mark(text: str) -> str:
    return re.sub(r"^\s*([.!?;:。！？；：])(?=\s|[}\)]|$)\s*", "", text, count=1)


def sentence_mark_to_chinese(mark: str) -> str:
    return {
        ".": "。",
        "?": "？",
        "!": "！",
        ";": "；",
        ":": "：",
    }.get(mark, mark)


def ends_with_sentence_mark(text: str) -> bool:
    return bool(re.search(r"[.!?;:。！？；：]\s*(?:\}|\)|\])*\s*$", text))


def ends_with_clause_mark(text: str) -> bool:
    return bool(re.search(r"[,，.!?;:。！？；：]\s*(?:\}|\)|\])*\s*$", text))


def protect_sentence_abbreviations(text: str) -> tuple[str, dict[str, str]]:
    protected: dict[str, str] = {}
    abbreviations = [
        "e.g.",
        "i.e.",
        "et al.",
        "Fig.",
        "Figs.",
        "Eq.",
        "Eqs.",
        "Sec.",
        "Secs.",
        "Tab.",
        "Tabs.",
        "No.",
        "vs.",
    ]
    for index, token in enumerate(abbreviations):
        placeholder = f"__PDF2ZH_SENT_ABBR_{index}__"
        if token in text:
            protected[placeholder] = token
            text = text.replace(token, placeholder)
    return text, protected


def restore_sentence_abbreviations(text: str, protected: dict[str, str]) -> str:
    for placeholder, token in protected.items():
        text = text.replace(placeholder, token)
    return text


def split_bilingual_sentences(text: str) -> list[str]:
    text = strip_bilingual_list_option_noise(text)
    text = strip_leading_sentence_continuation(text)
    text = compact_whitespace(text)
    if not text:
        return []
    protected_text, protected = protect_sentence_abbreviations(text)
    boundary = re.compile(r"(?<=[。！？；])|(?<=[.!?;:])\s+(?=(?:[A-Z0-9\\$]|\\[A-Za-z]))")
    chunks: list[str] = []
    start = 0
    for match in boundary.finditer(protected_text):
        chunk = protected_text[start : match.start()].strip()
        if chunk and not re.fullmatch(r"[.,;:!?，。；：！？\s]+", chunk):
            chunks.append(restore_sentence_abbreviations(chunk, protected))
        start = match.end()
    tail = protected_text[start:].strip()
    if tail and not re.fullmatch(r"[.,;:!?，。；：！？\s]+", tail):
        chunks.append(restore_sentence_abbreviations(tail, protected))
    return chunks or [restore_sentence_abbreviations(protected_text.strip(), protected)]


def group_chunks_to_count(chunks: list[str], target_count: int) -> list[str]:
    if target_count <= 0:
        return []
    if len(chunks) <= target_count:
        return chunks + [""] * (target_count - len(chunks))
    grouped: list[str] = []
    total = len(chunks)
    for index in range(target_count):
        start = round(index * total / target_count)
        end = round((index + 1) * total / target_count)
        grouped.append(" ".join(part for part in chunks[start:end] if part).strip())
    return grouped


def sentence_aligned_pairs(original: str, translated: str) -> list[tuple[str, str]]:
    original_sentences = split_bilingual_sentences(original)
    translated_sentences = split_bilingual_sentences(strip_repeated_segment_boundaries(original, translated))
    if not original_sentences and not translated_sentences:
        return []
    if len(original_sentences) == len(translated_sentences):
        return list(zip(original_sentences, translated_sentences))
    pair_count = max(1, min(len(original_sentences) or 1, len(translated_sentences) or 1))
    return list(zip(group_chunks_to_count(original_sentences, pair_count), group_chunks_to_count(translated_sentences, pair_count)))


def sentence_pair_body(original: str, translated: str) -> str:
    pairs: list[str] = []
    for original_sentence, translated_sentence in sentence_aligned_pairs(original, translated):
        original_sentence = original_sentence.strip()
        translated_sentence = translated_sentence.strip()
        pieces: list[str] = []
        if original_sentence:
            pieces.append(original_sentence)
        green = green_sentence(translated_sentence)
        if green:
            pieces.append(green)
        if pieces:
            pairs.append(" ".join(pieces))
    return " ".join(pairs)


def sentence_pair_block(original: str, translated: str) -> str:
    body = sentence_pair_body(original, translated)
    if not body:
        return ""
    return f"\n\n{body}\n\n"


def merge_bilingual_command_arg(original_arg: str, translated_arg: str) -> str:
    zh = translated_arg.strip()
    if not zh or compact_whitespace(zh) == compact_whitespace(original_arg):
        return original_arg
    return f"{original_arg} {{{green_inline(zh)}}}"


def with_bilingual_color_support(text: str) -> str:
    if r"\usepackage{xcolor}" not in text and not re.search(r"\\usepackage\[[^\]]*\]\{xcolor\}", text):
        docclass = re.search(r"\\documentclass(?:\[[^\]]*\])?\{[^}]+\}\s*", text)
        load = "\\usepackage{xcolor}\n"
        if docclass:
            text = text[: docclass.end()] + load + text[docclass.end() :]
        else:
            text = load + text
    define = rf"\definecolor{{{BILINGUAL_COLOR_NAME}}}{{RGB}}{{0,128,0}}"
    if define not in text:
        begin_doc = re.search(r"\\begin\{document\}", text)
        insertion = define + "\n"
        if begin_doc:
            text = text[: begin_doc.start()] + insertion + text[begin_doc.start() :]
        else:
            text = insertion + text
    return text


def with_bilingual_frontmatter_spacing(text: str) -> str:
    return re.sub(
        r"(\\renewcommand\{\\thefootnote\}\{\\arabic\{footnote\}\}\s*)(\\begin\{abstract\})",
        r"\1\n\\vspace*{7.0em}\n\2",
        text,
        count=1,
    )


def with_bibliography_input(text: str, bbl_name: str) -> str:
    if (
        re.search(r"\\(?:input|bibliography)\{[^{}]*\.?bbl[^{}]*\}", text)
        or r"\bibliography{" in text
        or r"\begin{thebibliography}" in text
    ):
        return text
    insertion = "{\n    \\small\n    " + rf"\input{{{bbl_name}}}" + "\n}\n\n"
    text, count = re.subn(
        r"\{\s*\\small\s*\}\s*(?=\\newpage\s*\\appendix)",
        lambda _match: insertion,
        text,
        count=1,
        flags=re.S,
    )
    if count:
        return text
    return re.sub(r"(?=\\newpage\s*\\appendix)", insertion, text, count=1)


def translated_caption_arg(translated: str, translated_cmd: dict | None) -> str:
    if translated_cmd:
        return translated_cmd["arg"]
    return re.sub(r"^\s*\\caption(?:\*)?(?:\s*\[[^\]]*\])*\s*\{", "", translated).strip()


def bilingualize_caption_segment(original: str, translated: str) -> str | None:
    original_cmd = first_latex_command(original, {"caption"})
    translated_cmd = first_latex_command(translated, {"caption"})
    if not original_cmd:
        caption_open = re.search(r"\\caption(?:\*)?(?:\s*\[[^\]]*\])*\s*\{", original)
        if not caption_open:
            return None
        translated_arg = translated_caption_arg(translated, translated_cmd)
        green = green_inline(translated_arg)
        if not green:
            return original
        trailing = original[len(original.rstrip()) :]
        return original.rstrip() + f" {{{green}}}" + trailing

    translated_arg = translated_caption_arg(translated, translated_cmd)
    merged_arg = merge_bilingual_command_arg(original_cmd["arg"], translated_arg)
    merged_caption = original_cmd["open"] + merged_arg + "}"
    output = original[: original_cmd["start"]] + merged_caption + original[original_cmd["end"] :]
    translated_tail = strip_label_commands(translated[translated_cmd["end"] :]).strip() if translated_cmd else ""
    if translated_tail:
        output += green_block(translated_tail)
    return output


def bilingualize_structural_segment(original: str, translated: str) -> str | None:
    start = len(original) - len(original.lstrip())
    translated_start = len(translated) - len(translated.lstrip())
    original_cmd = latex_command_at(original, start, STRUCTURAL_BILINGUAL_COMMANDS)
    translated_cmd = latex_command_at(translated, translated_start, STRUCTURAL_BILINGUAL_COMMANDS)
    if not original_cmd or not translated_cmd or original_cmd["name"] != translated_cmd["name"]:
        return None

    merged_arg = merge_bilingual_command_arg(original_cmd["arg"], translated_cmd["arg"])
    merged_command = original_cmd["open"] + merged_arg + "}"
    output = original[: original_cmd["start"]] + merged_command
    original_tail = original[original_cmd["end"] :]
    translated_tail = strip_label_commands(translated[translated_cmd["end"] :])
    original_tail_start = len(original_tail) - len(original_tail.lstrip())
    translated_tail_start = len(translated_tail) - len(translated_tail.lstrip())
    if latex_command_at(original_tail, original_tail_start, STRUCTURAL_BILINGUAL_COMMANDS) and latex_command_at(
        translated_tail,
        translated_tail_start,
        STRUCTURAL_BILINGUAL_COMMANDS,
    ):
        output += bilingualize_segment(original_tail, translated_tail)
    else:
        output += sentence_pair_block(original_tail, translated_tail)
    return output


def bilingualize_item_segment(original: str, translated: str) -> str | None:
    original = strip_bilingual_list_option_noise(original)
    translated = strip_bilingual_list_option_noise(translated)
    item_pattern = re.compile(r"(?m)(\s*\\item(?:\[[^\]]*\])?\s*)")
    original_matches = list(item_pattern.finditer(original))
    translated_matches = list(item_pattern.finditer(translated))
    if not original_matches or not translated_matches:
        return None
    if original[: original_matches[0].start()].strip() or translated[: translated_matches[0].start()].strip():
        return None
    if len(original_matches) != len(translated_matches):
        return None

    pieces: list[str] = []
    for index, original_match in enumerate(original_matches):
        translated_match = translated_matches[index]
        original_body_start = original_match.end()
        original_body_end = original_matches[index + 1].start() if index + 1 < len(original_matches) else len(original)
        translated_body_start = translated_match.end()
        translated_body_end = translated_matches[index + 1].start() if index + 1 < len(translated_matches) else len(translated)
        pieces.append(original_match.group(1))
        pieces.append(sentence_pair_body(original[original_body_start:original_body_end], translated[translated_body_start:translated_body_end]))
    return "".join(pieces)


def strip_repeated_executable_commands(original: str, translated: str) -> str:
    output = translated
    duplicate_patterns = [
        r"\\maketitle\b\s*",
        r"(?m)^\\renewcommand\{\\thefootnote\}.*(?:\r?\n)?",
    ]
    for pattern in duplicate_patterns:
        if re.search(pattern, original):
            output = re.sub(pattern, "", output)
    return output


OPEN_ARGUMENT_TAIL_COMMANDS = {
    "resizebox": 2,
    "scalebox": 1,
}


def parse_balanced_brace_argument(text: str, start: int) -> int | None:
    if start >= len(text) or text[start] != "{":
        return None
    depth = 1
    index = start + 1
    while index < len(text):
        char = text[index]
        if char == "\\":
            index += 2
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index + 1
        index += 1
    return None


def trailing_open_argument_command(text: str) -> tuple[int, str] | None:
    stripped_end = len(text.rstrip())
    candidate = text[:stripped_end]
    if not candidate.endswith("{"):
        return None
    command_pattern = re.compile(r"\\([A-Za-z@]+)\*?\b")
    for match in reversed(list(command_pattern.finditer(candidate))):
        command = match.group(1)
        arg_count = OPEN_ARGUMENT_TAIL_COMMANDS.get(command)
        if arg_count is None:
            continue
        index = match.end()
        for _ in range(arg_count):
            while index < len(candidate) and candidate[index].isspace():
                index += 1
            parsed_end = parse_balanced_brace_argument(candidate, index)
            if parsed_end is None:
                break
            index = parsed_end
        else:
            while index < len(candidate) and candidate[index].isspace():
                index += 1
            if index == len(candidate) - 1 and candidate[index] == "{":
                return match.start(), text[match.start():]
    return None


def strip_repeated_segment_boundaries(original: str, translated: str) -> str:
    output = strip_repeated_executable_commands(original, translated)
    if re.match(r"^\s*\}(?:\\\\)?", original) and re.match(r"^\s*\}(?:\\\\)?", output):
        output = re.sub(r"^\s*\}(?:\\\\)?\s*", "", output, count=1)
    if trailing_open_argument_command(original):
        translated_tail = trailing_open_argument_command(output)
        if translated_tail:
            tail_start, _tail = translated_tail
            output = output[:tail_start].rstrip()
    return output


def bilingualize_open_argument_tail_segment(original: str, translated: str) -> str | None:
    tail = trailing_open_argument_command(original)
    if not tail:
        return None
    tail_start, _tail_text = tail
    translated_body = strip_repeated_segment_boundaries(original, translated)
    green = green_block(translated_body)
    if not green:
        return original
    return original[:tail_start] + green + original[tail_start:]


def escaped_at(text: str, index: int) -> bool:
    backslashes = 0
    cursor = index - 1
    while cursor >= 0 and text[cursor] == "\\":
        backslashes += 1
        cursor -= 1
    return backslashes % 2 == 1


def update_caption_arg_depth(depth: int, text: str, command_names: set[str] | None = None) -> int:
    names = command_names or {"caption"}
    command_pattern = "|".join(sorted(re.escape(name) for name in names))
    caption_open = re.compile(rf"\\(?:{command_pattern})(?:\*)?(?:\s*\[[^\]]*\])*\s*\{{")
    index = 0
    while index < len(text):
        if depth == 0:
            match = caption_open.search(text, index)
            if not match:
                break
            depth = 1
            index = match.end()
            continue
        char = text[index]
        if char == "{" and not escaped_at(text, index):
            depth += 1
        elif char == "}" and not escaped_at(text, index):
            depth = max(0, depth - 1)
        index += 1
    return depth


def bilingualize_caption_text_fragment(original: str, translated: str) -> str:
    if compact_whitespace(original) == compact_whitespace(translated):
        return original
    green = green_inline(translated)
    if not green:
        return original
    trailing = original[len(original.rstrip()) :]
    return original.rstrip() + f" {{{green}}}" + trailing


def bilingualize_segment(original: str, translated: str) -> str:
    original = strip_bilingual_list_option_noise(original)
    translated = strip_bilingual_list_option_noise(translated)
    if compact_whitespace(original) == compact_whitespace(translated):
        return original
    for builder in (
        bilingualize_caption_segment,
        bilingualize_structural_segment,
        bilingualize_item_segment,
        bilingualize_open_argument_tail_segment,
    ):
        output = builder(original, translated)
        if output is not None:
            return output
    if brace_balance(original) != 0:
        return bilingualize_caption_text_fragment(original, translated)
    return sentence_pair_block(original, translated)


def cmd_apply_bilingual(args: argparse.Namespace) -> None:
    work = Path(args.work).resolve()
    state_path = work / "pipeline_state.json"
    if not state_path.is_file():
        die(f"missing state file: {state_path}")
    state = json.loads(state_path.read_text(encoding="utf-8"))
    translations = {row["id"]: row.get("translation", "") for row in load_jsonl(Path(args.translations).resolve())}
    if not translations:
        die("translation JSONL is empty")

    pieces: list[str] = []
    missing: list[str] = []
    reverted: list[str] = []
    caption_arg_depth = 0
    nodes = state["nodes"]
    index = 0
    while index < len(nodes):
        node = nodes[index]
        if node["kind"] == PRESERVE:
            pieces.append(node["text"])
            caption_arg_depth = update_caption_arg_depth(caption_arg_depth, node["text"], INLINE_BILINGUAL_ARG_COMMANDS)
            index += 1
            continue

        original_parts: list[str] = []
        fixed_parts: list[str] = []
        while index < len(nodes) and nodes[index]["kind"] == TRANSLATE:
            translate_node = nodes[index]
            segment_id = translate_node["segment_id"]
            original_part = translate_node["text"]
            translated = translations.get(segment_id)
            if translated is None:
                missing.append(segment_id)
                translated = original_part
            fixed_part = fix_translation(translated, original_part)
            original_leading_mark = leading_sentence_mark(original_part)
            fixed_leading_mark = leading_sentence_mark(fixed_part)
            if fixed_parts and (fixed_leading_mark or original_leading_mark) and not ends_with_sentence_mark(fixed_parts[-1]):
                fixed_parts[-1] += sentence_mark_to_chinese(fixed_leading_mark or original_leading_mark or ".")
            if fixed_leading_mark:
                fixed_part = strip_leading_sentence_mark(fixed_part)
            original_leading_comma = re.match(r"^\s*[,，]\s*", original_part)
            fixed_leading_comma = re.match(r"^\s*[,，]\s*", fixed_part)
            if fixed_parts and (original_leading_comma or fixed_leading_comma):
                if not ends_with_clause_mark(fixed_parts[-1]):
                    fixed_parts[-1] += "，"
                if fixed_leading_comma:
                    fixed_part = fixed_part[fixed_leading_comma.end() :]
            if fixed_part == original_part and translated != original_part:
                reverted.append(segment_id)
            original_parts.append(original_part)
            fixed_parts.append(fixed_part)
            index += 1

        preserve_remainder: str | None = None
        if index < len(nodes) and nodes[index]["kind"] == PRESERVE:
            punctuation_match = re.fullmatch(r"([.!?。！？])(\s*)", nodes[index]["text"], flags=re.S)
            leading_punctuation_match = re.match(r"^([.!?。！？])(\s+.*)$", nodes[index]["text"], flags=re.S)
            if (punctuation_match or leading_punctuation_match) and original_parts:
                mark = (punctuation_match or leading_punctuation_match).group(1)
                preserve_remainder = leading_punctuation_match.group(2) if leading_punctuation_match else None
                if not re.search(r"[.!?。！？]\s*$", original_parts[-1]):
                    original_parts[-1] += mark
                if fixed_parts and not re.search(r"[.!?。！？]\s*$", fixed_parts[-1]):
                    fixed_parts[-1] += "。" if mark in ".!?" else mark
                index += 1

        original = "".join(original_parts)
        fixed = "".join(fixed_parts)
        rendered = (
            bilingualize_caption_text_fragment(original, fixed)
            if caption_arg_depth > 0
            else bilingualize_segment(original, fixed)
        )
        pieces.append(rendered)
        caption_arg_depth = update_caption_arg_depth(caption_arg_depth, rendered, INLINE_BILINGUAL_ARG_COMMANDS)
        if preserve_remainder is not None:
            pieces.append(preserve_remainder)
            caption_arg_depth = update_caption_arg_depth(caption_arg_depth, preserve_remainder, INLINE_BILINGUAL_ARG_COMMANDS)
    if missing:
        print(f"warning: missing translations for {len(missing)} segments: {', '.join(missing[:10])}", file=sys.stderr)
    if reverted:
        print(f"warning: reverted {len(reverted)} risky bilingual translations: {', '.join(reverted[:10])}", file=sys.stderr)

    out = work / f"{BILINGUAL_MERGED_BASENAME}.tex"
    final_text = "".join(pieces)
    final_text = normalize_frontmatter_content(final_text)
    final_text = with_bilingual_color_support(final_text)
    final_text = with_abstract_name(final_text, rf"Abstract {{\textcolor{{{BILINGUAL_COLOR_NAME}}}{{摘要}}}}")
    final_text = with_bilingual_frontmatter_spacing(final_text)
    final_text = with_bibliography_input(final_text, f"{BILINGUAL_MERGED_BASENAME}.bbl")
    out.write_text(sanitize_latex_source(final_text), encoding="utf-8")
    print(out)


def cmd_compile(args: argparse.Namespace) -> None:
    work = Path(args.work).resolve()
    main = args.main
    tex = work / f"{main}.tex"
    if not tex.is_file():
        die(f"missing {tex}; run apply first")
    compiler = args.compiler or compiler_for(tex)

    compilers = [compiler]
    if args.compiler is None and compiler != "lualatex" and shutil.which("lualatex"):
        compilers.append("lualatex")

    pdf = work / f"{main}.pdf"
    for index, candidate in enumerate(compilers):
        if index:
            print(f"warning: {compiler} failed; retrying with {candidate}", file=sys.stderr)
        produced, ok = compile_attempt(candidate, work, main, args.timeout_seconds)
        if produced:
            issues = collect_critical_latex_issues(work / f"{main}.log")
            if issues:
                for line in issues[:20]:
                    print(line, file=sys.stderr)
                die("LaTeX produced a PDF but the log still contains critical errors")
            if not ok:
                print("warning: LaTeX returned a non-zero status, but the PDF was produced", file=sys.stderr)
            print(pdf)
            return

    log = work / f"{main}.log"
    if log.exists():
        print(log.read_text(encoding="utf-8", errors="replace")[-8000:], file=sys.stderr)
    die("LaTeX compilation failed")


def load_quality_issues(json_path: Path) -> list[dict]:
    if not json_path.is_file():
        return []
    try:
        payload = json.loads(json_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    issues = payload.get("issues", [])
    return issues if isinstance(issues, list) else []


def blocking_quality_issues(json_path: Path) -> list[dict]:
    return [
        issue
        for issue in load_quality_issues(json_path)
        if issue.get("severity") == "error" or issue.get("kind") in BLOCKING_QUALITY_KINDS
    ]


def repair_translation_inventory(work: Path, translations_path: Path) -> int:
    segments_path = work / ENGLISH_SEGMENTS_NAME
    if not segments_path.is_file() or not translations_path.is_file():
        return 0
    segments = {row.get("id", ""): row.get("text", "") for row in load_jsonl(segments_path) if row.get("id")}
    rows = load_jsonl(translations_path)
    changed = 0
    for row in rows:
        segment_id = row.get("id")
        original = segments.get(segment_id or "")
        translated = row.get("translation", "")
        if not original or not translated:
            continue
        fixed = fix_translation(translated, original)
        if fixed != translated:
            row["translation"] = fixed
            changed += 1
    if changed:
        write_jsonl(translations_path, rows)
    return changed


def write_quality_report_with_repair(
    work: Path,
    translations_path: Path,
    *,
    max_repair_passes: int = 2,
) -> tuple[Path, Path, int, list[dict]]:
    quality_json, quality_md, quality_issue_count = write_quality_report(work, translations_path)
    for _ in range(max_repair_passes):
        blockers = blocking_quality_issues(quality_json)
        if not blockers:
            return quality_json, quality_md, quality_issue_count, []
        changed = repair_translation_inventory(work, translations_path)
        if not changed:
            return quality_json, quality_md, quality_issue_count, blockers
        log(f"Quality auto repair: normalized {changed} translated segment(s)")
        cmd_apply(argparse.Namespace(work=str(work), translations=str(translations_path)))
        quality_json, quality_md, quality_issue_count = write_quality_report(work, translations_path)
    return quality_json, quality_md, quality_issue_count, blocking_quality_issues(quality_json)


DOC2X_API_KEY_ENV = "DOC2X_API_KEY"


def doc2x_config_help() -> str:
    return (
        "DOC2X API key is not configured; missing DOC2X_API_KEY. "
        "Put DOC2X_API_KEY=... in .env or pass --doc2x-api-key to run "
        "(--api-key for the convert subcommand). "
        "For a low-fidelity smoke test, pass --method text explicitly."
    )


def choose_conversion_method(requested: str) -> str:
    if requested != "auto":
        return requested
    if os.environ.get(DOC2X_API_KEY_ENV):
        return "doc2x"
    die(doc2x_config_help())


def config_present(value: str | None) -> bool:
    return bool(value and value.strip())


def translation_config_status(
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
) -> dict[str, bool]:
    return {
        TRANSLATION_API_KEY_ENV: config_present(api_key or os.environ.get(TRANSLATION_API_KEY_ENV)),
        TRANSLATION_BASE_URL_ENV: config_present(base_url or os.environ.get(TRANSLATION_BASE_URL_ENV)),
        TRANSLATION_MODEL_ENV: config_present(model or os.environ.get(TRANSLATION_MODEL_ENV)),
    }


def missing_translation_config(
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
) -> list[str]:
    return [key for key, present in translation_config_status(api_key=api_key, base_url=base_url, model=model).items() if not present]


def effective_doc2x_api_key(api_key: str | None = None) -> str | None:
    return api_key or os.environ.get(DOC2X_API_KEY_ENV)


def require_run_translation_config(args: argparse.Namespace) -> None:
    missing = missing_translation_config(
        api_key=args.translation_api_key,
        base_url=args.translation_base_url,
        model=args.translation_model,
    )
    if missing:
        die(translation_config_help(missing))


def should_preflight_doc2x_for_run(args: argparse.Namespace) -> bool:
    if args.project or args.method not in {"auto", "doc2x"}:
        return False
    if args.url and arxiv_id_from_url(args.url):
        return False
    return True

def maybe_existing_project(project: Path) -> bool:
    return project.is_dir() and any(project.rglob("*.tex"))

def maybe_existing_prepare(work: Path) -> bool:
    return (work / "pipeline_state.json").is_file() and (work / ENGLISH_SEGMENTS_NAME).is_file()


def line_number_at(text: str, offset: int) -> int:
    return text.count("\n", 0, max(0, offset)) + 1


def snippet_at(text: str, offset: int, length: int = 180) -> str:
    start = max(0, offset - length // 2)
    end = min(len(text), offset + length // 2)
    return compact_whitespace(text[start:end])


def add_quality_issue(
    issues: list[dict],
    *,
    kind: str,
    severity: str,
    source: str,
    snippet: str,
    suggestion: str,
    line: int | None = None,
    segment_id: str | None = None,
) -> None:
    issue = {
        "kind": kind,
        "severity": severity,
        "source": source,
        "snippet": snippet,
        "suggestion": suggestion,
    }
    if line is not None:
        issue["line"] = line
    if segment_id:
        issue["segment_id"] = segment_id
    issues.append(issue)


def collect_quality_issues_from_text(text: str, *, source: str, segment_id: str | None = None) -> list[dict]:
    issues: list[dict] = []
    checks = [
        (
            "prompt_leak",
            "error",
            re.compile(r"(以下为翻译后的\s*LaTeX\s*文本|以下为翻译后的文本|Translated LaTeX text|Here is the translated|Here is the translation)", re.I),
            "删除模型回复前缀，只保留论文正文译文。",
        ),
        (
            "bad_reference_key",
            "error",
            bad_reference_command_pattern(),
            "恢复原始引用 key，不能保留空引用或省略号引用。",
        ),
        (
            "placeholder_leak",
            "error",
            re.compile(r"(__LATEX_BLOCK_\d+__|\\_\\_LATEX\\_BLOCK\\_\d+\\_\\_)"),
            "恢复或删除内部占位符，最终 TeX/PDF 不应出现占位符文本。",
        ),
        (
            "double_escaped_reference",
            "error",
            re.compile(rf"\\\\(?:{REF_LIKE_COMMANDS})\*?(?:\[[^\]]*\])*\{{"),
            "引用命令不应被写成双反斜杠；应恢复为单个反斜杠。",
        ),
        (
            "malformed_reference_command",
            "error",
            re.compile(
                rf"\\(?:{REF_LIKE_COMMANDS})\*?(?:\[[^\]]*\])*\s*"
                rf"\\(?:{REF_LIKE_COMMANDS})\*?(?:\[[^\]]*\])*\{{"
            ),
            "引用命令被重复拼接；应保留一个引用命令并恢复正确 key。",
        ),
        (
            "latex_control_word_split",
            "error",
            re.compile(r"\\item\s+sep\s*-?\d"),
            "LaTeX 控制词被拆开；应恢复为 \\itemsep。",
        ),
        (
            "markdown_artifact",
            "warn",
            re.compile(r"(?<!\\)(?:\*\*[^*\n]+\*\*|__[^_\n]+__|(?<!`)`(?!`)[^`\n]+(?<!`)`(?!`))"),
            "清理 Markdown 标记，必要时改用原 LaTeX 强调命令。",
        ),
    ]
    for kind, severity, pattern, suggestion in checks:
        for match in pattern.finditer(text):
            add_quality_issue(
                issues,
                kind=kind,
                severity=severity,
                source=source,
                line=line_number_at(text, match.start()) if source.endswith(".tex") else None,
                segment_id=segment_id,
                snippet=snippet_at(text, match.start()),
                suggestion=suggestion,
            )
    for start, _end, command in iter_ref_like_commands(text):
        argument = reference_command_argument(command)
        if "\\" in argument or "\n" in argument or "{" in argument or "}" in argument:
            add_quality_issue(
                issues,
                kind="malformed_reference_key",
                severity="error",
                source=source,
                line=line_number_at(text, start) if source.endswith(".tex") else None,
                segment_id=segment_id,
                snippet=snippet_at(text, start),
                suggestion="引用 key 中不应包含正文、嵌套命令或换行；应恢复原始引用 key。",
            )

    for line_no, line in enumerate(text.splitlines(), 1):
        if re.search(r"\S.{0,120}\\(?:section|subsection|subsubsection)\{", line):
            add_quality_issue(
                issues,
                kind="latex_section_inside_prose",
                severity="error",
                source=source,
                line=line_no if source.endswith(".tex") else None,
                segment_id=segment_id,
                snippet=compact_whitespace(line),
                suggestion="检查是否把章节命令误插入正文；正文中的章节引用应使用 \\ref 或自然语言。",
            )
        cjk_count = sum("\u4e00" <= ch <= "\u9fff" for ch in line)
        if cjk_count < 8:
            continue
        prose_line = re.sub(r"\\[A-Za-z]+\*?(?:\[[^\]]*\])?(?:\{[^{}]*\})?", " ", line)
        residue_patterns = [
            r"\b(?:and|or|with|as|by|from|to|for|of|in|on)\s+[A-Za-z][A-Za-z-]*",
            r"\b(?:Nevertheless|However|Therefore|Overall),?\s+[A-Za-z]",
            r"\b(?:Table|Figure|Section)~?\\ref",
        ]
        if any(re.search(pattern, prose_line) for pattern in residue_patterns) or re.search(r"\b(?:Table|Figure|Section)~?\\ref", line):
            add_quality_issue(
                issues,
                kind="english_residue",
                severity="warn",
                source=source,
                line=line_no if source.endswith(".tex") else None,
                segment_id=segment_id,
                snippet=compact_whitespace(line),
                suggestion="人工复查该句是否残留英文连接词、说明短语或未翻译正文。",
            )
    list_pattern = re.compile(r"\\begin\{(enumerate|itemize|description)\}(.*?)\\end\{\1\}", re.S)
    for match in list_pattern.finditer(text):
        body = match.group(2).lstrip()
        if body.startswith("["):
            option_depth = 0
            option_end = None
            for index, char in enumerate(body):
                if char == "[":
                    option_depth += 1
                elif char == "]":
                    option_depth -= 1
                    if option_depth == 0:
                        option_end = index + 1
                        break
            if option_end is not None:
                body = body[option_end:].lstrip()
        if body and not body.startswith(r"\item"):
            add_quality_issue(
                issues,
                kind="missing_list_item",
                severity="error",
                source=source,
                line=line_number_at(text, match.start()) if source.endswith(".tex") else None,
                segment_id=segment_id,
                snippet=snippet_at(text, match.start()),
                suggestion="列表环境中的每个条目必须以 \\item 开头；模型修稿时应恢复被删除的 \\item。",
            )
    return issues


def write_quality_report(work: Path, translations_path: Path | None = None) -> tuple[Path, Path, int]:
    tex_path = work / f"{CHINESE_MERGED_BASENAME}.tex"
    issues: list[dict] = []
    tex_text = ""
    tex_text_compact = ""
    if tex_path.is_file():
        tex_text = tex_path.read_text(encoding="utf-8", errors="replace")
        tex_text_compact = compact_whitespace(tex_text)
        issues.extend(collect_quality_issues_from_text(tex_text, source=tex_path.name))

    segments: dict[str, str] = {}
    segments_path = work / ENGLISH_SEGMENTS_NAME
    if segments_path.is_file():
        segments = {row.get("id", ""): row.get("text", "") for row in load_jsonl(segments_path) if row.get("id")}
    check_translations = translations_path or work / CHINESE_REVIEWED_TRANSLATIONS_NAME
    if check_translations.is_file():
        for row in load_jsonl(check_translations):
            segment_id = row.get("id")
            translated = row.get("translation", "")
            translated_compact = compact_whitespace(translated)
            if tex_text_compact and translated_compact:
                probe = translated_compact[: min(120, len(translated_compact))]
                if len(probe) >= 24 and probe not in tex_text_compact:
                    continue
            original = segments.get(segment_id or "", "")
            if segment_id and original and is_probably_untranslated(original, translated):
                add_quality_issue(
                    issues,
                    kind="likely_untranslated_segment",
                    severity="warn",
                    source=check_translations.name,
                    segment_id=segment_id,
                    snippet=compact_whitespace(translated[:220]),
                    suggestion="该 segment 疑似英文残留过多；模型二次审阅时应对照原文重译。",
                )
            if segment_id and translated:
                issues.extend(collect_quality_issues_from_text(translated, source=check_translations.name, segment_id=segment_id))

    payload = {"issue_count": len(issues), "issues": issues}
    json_path = work / CHINESE_QUALITY_REPORT_JSON_NAME
    md_path = work / CHINESE_QUALITY_REPORT_MD_NAME
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = ["# 中文译稿质量审阅清单", "", f"- Issue count: {len(issues)}", ""]
    if issues:
        for index, issue in enumerate(issues, 1):
            location = []
            if "line" in issue:
                location.append(f"line {issue['line']}")
            if "segment_id" in issue:
                location.append(str(issue["segment_id"]))
            where = f" ({', '.join(location)})" if location else ""
            lines.append(f"{index}. **{issue['severity']} / {issue['kind']}**{where}")
            lines.append(f"   - Snippet: `{issue['snippet']}`")
            lines.append(f"   - Action: {issue['suggestion']}")
    else:
        lines.append("No obvious machine-detectable issues were found. The model should still review the PDF visually.")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path, len(issues)

def write_run_summary(
    path: Path,
    *,
    status: str = "succeeded",
    error: str | None = None,
    method: str,
    source: str,
    project: Path,
    work: Path,
    pdf: Path | None,
    english_tex: Path | None,
    tex: Path | None,
    quality_report_json: Path,
    quality_report_md: Path,
    quality_issue_count: int,
    bilingual_pdf: Path | None = None,
    bilingual_tex: Path | None = None,
    vision_pack: Path | None = None,
    bilingual_vision_pack: Path | None = None,
    vision_pack_note: str | None = None,
    bilingual_vision_pack_note: str | None = None,
) -> None:
    summary = {
        "status": status,
        "method": method,
        "source": source,
        "project": str(project),
        "work": str(work),
        "work_pdf": str(work / f"{CHINESE_MERGED_BASENAME}.pdf"),
        "work_bilingual_pdf": str(work / f"{BILINGUAL_MERGED_BASENAME}.pdf"),
        "segments_english": str(work / ENGLISH_SEGMENTS_NAME),
        "glossary_english": str(work / ENGLISH_GLOSSARY_NAME),
        "translations": str(work / CHINESE_TRANSLATIONS_NAME),
        "reviewed_translations": str(work / CHINESE_REVIEWED_TRANSLATIONS_NAME),
        "work_english_tex": str(work / f"{ENGLISH_MERGED_BASENAME}.tex"),
        "work_tex": str(work / f"{CHINESE_MERGED_BASENAME}.tex"),
        "work_bilingual_tex": str(work / f"{BILINGUAL_MERGED_BASENAME}.tex"),
        "consistency_report": str(work / CHINESE_CONSISTENCY_REPORT_NAME),
        "quality_report_json": str(quality_report_json),
        "quality_report_md": str(quality_report_md),
        "quality_issue_count": quality_issue_count,
        "skill_home": str(skill_home_dir()),
        "output_root": str(skill_output_dir()),
        "tmp_root": str(skill_tmp_dir()),
    }
    if error:
        summary["error"] = error
    if pdf is not None:
        summary["pdf"] = str(pdf)
    if english_tex is not None:
        summary["english_tex"] = str(english_tex)
    if tex is not None:
        summary["tex"] = str(tex)
    if bilingual_pdf is not None:
        summary["bilingual_pdf"] = str(bilingual_pdf)
    if bilingual_tex is not None:
        summary["bilingual_tex"] = str(bilingual_tex)
    if vision_pack is not None:
        summary["vision_pack"] = str(vision_pack)
    if bilingual_vision_pack is not None:
        summary["bilingual_vision_pack"] = str(bilingual_vision_pack)
    if vision_pack_note:
        summary["vision_pack_note"] = vision_pack_note
    if bilingual_vision_pack_note:
        summary["bilingual_vision_pack_note"] = bilingual_vision_pack_note
    if is_wsl():
        windows_fields = {
            "project_windows": windows_visible_path(project),
            "work_windows": windows_visible_path(work),
            "pdf_windows": windows_visible_path(pdf) if pdf else None,
            "bilingual_pdf_windows": windows_visible_path(bilingual_pdf) if bilingual_pdf else None,
            "work_pdf_windows": windows_visible_path(work / f"{CHINESE_MERGED_BASENAME}.pdf"),
            "work_bilingual_pdf_windows": windows_visible_path(work / f"{BILINGUAL_MERGED_BASENAME}.pdf"),
            "segments_english_windows": windows_visible_path(work / ENGLISH_SEGMENTS_NAME),
            "glossary_english_windows": windows_visible_path(work / ENGLISH_GLOSSARY_NAME),
            "translations_windows": windows_visible_path(work / CHINESE_TRANSLATIONS_NAME),
            "reviewed_translations_windows": windows_visible_path(work / CHINESE_REVIEWED_TRANSLATIONS_NAME),
            "english_tex_windows": windows_visible_path(english_tex) if english_tex else None,
            "tex_windows": windows_visible_path(tex) if tex else None,
            "bilingual_tex_windows": windows_visible_path(bilingual_tex) if bilingual_tex else None,
            "work_english_tex_windows": windows_visible_path(work / f"{ENGLISH_MERGED_BASENAME}.tex"),
            "work_tex_windows": windows_visible_path(work / f"{CHINESE_MERGED_BASENAME}.tex"),
            "work_bilingual_tex_windows": windows_visible_path(work / f"{BILINGUAL_MERGED_BASENAME}.tex"),
            "consistency_report_windows": windows_visible_path(work / CHINESE_CONSISTENCY_REPORT_NAME),
            "quality_report_json_windows": windows_visible_path(quality_report_json),
            "quality_report_md_windows": windows_visible_path(quality_report_md),
            "skill_home_windows": windows_visible_path(skill_home_dir()),
            "output_root_windows": windows_visible_path(skill_output_dir()),
            "tmp_root_windows": windows_visible_path(skill_tmp_dir()),
            "vision_pack_windows": windows_visible_path(vision_pack) if vision_pack else None,
            "bilingual_vision_pack_windows": windows_visible_path(bilingual_vision_pack) if bilingual_vision_pack else None,
        }
        summary.update({k: v for k, v in windows_fields.items() if v})
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

def cmd_run(args: argparse.Namespace) -> None:
    require_run_translation_config(args)
    if should_preflight_doc2x_for_run(args) and not config_present(effective_doc2x_api_key(args.doc2x_api_key)):
        die(doc2x_config_help())
    source_hint = args.project or args.pdf or args.url or "run"
    output_dir = Path(args.output_dir).expanduser().resolve() if args.output_dir else default_task_output_dir(source_hint)
    output_dir.mkdir(parents=True, exist_ok=True)
    convert_dir = output_dir / "convert"
    arxiv_convert_dir = convert_dir / "arxiv_source"
    work_dir = output_dir / "zh"
    source_pdf_for_pack: Path | None = None
    log_path_hint("Skill home", skill_home_dir())
    log_path_hint("Task output root", skill_output_dir())
    log_path_hint("Task output dir", output_dir)

    if args.project:
        project = Path(args.project).resolve()
        if not project.is_dir():
            die(f"project folder not found: {project}")
        if args.source_pdf:
            source_pdf_for_pack = persist_source_pdf(Path(args.source_pdf).expanduser().resolve(), output_dir)
        method = "project"
        source = str(project)
    else:
        method = args.method
        source = args.url or str(Path(args.pdf).resolve())
        arxiv_id = arxiv_id_from_url(args.url) if args.url else None
        if arxiv_id and maybe_existing_project(arxiv_convert_dir / "project") and not args.force_convert:
            project = arxiv_convert_dir / "project"
            pdf_candidates = sorted(arxiv_convert_dir.glob("*.pdf"))
            source_pdf_for_pack = pdf_candidates[0] if pdf_candidates else None
            method = "arxiv-src"
            log(f"Run: reusing arXiv source project {project}")
        elif maybe_existing_project(convert_dir / "project") and not args.force_convert:
            project = convert_dir / "project"
            log(f"Run: reusing converted project {project}")
        else:
            if convert_dir.exists() and args.force_convert:
                shutil.rmtree(convert_dir)
            pdf_path: Path | None = None
            if args.url:
                arxiv_project = download_arxiv_source_project(args.url, arxiv_convert_dir)
                if arxiv_project is not None:
                    project, source_pdf_for_pack = arxiv_project
                    method = "arxiv-src"
                    source = args.url
            if method != "arxiv-src" and pdf_path is None:
                method = choose_conversion_method(args.method)
                pdf_path = persist_source_pdf(Path(args.pdf).expanduser().resolve(), output_dir) if args.pdf else None
                if pdf_path is not None:
                    source = str(pdf_path)
            if method != "arxiv-src" and args.url and pdf_path is None:
                pdf_path = download_remote_pdf(args.url, convert_dir / "remote_source")
            if method != "arxiv-src":
                source_pdf_for_pack = pdf_path.resolve() if pdf_path else None
                if method == "doc2x":
                    if pdf_path is None or not pdf_path.is_file():
                        die("--pdf is required for DOC2X conversion")
                    project = convert_doc2x(pdf_path, convert_dir, args.doc2x_api_key, args.doc2x_model)
                elif method == "mathpix":
                    if pdf_path is None or not pdf_path.is_file():
                        die("--pdf is required for Mathpix conversion")
                    project = convert_mathpix(pdf_path, convert_dir, args.mathpix_app_id, args.mathpix_app_key)
                else:
                    if pdf_path is None or not pdf_path.is_file():
                        die("--pdf is required for text fallback conversion")
                    project = convert_text_fallback(pdf_path, convert_dir)

    if args.force_prepare and work_dir.exists():
        shutil.rmtree(work_dir)
    if not maybe_existing_prepare(work_dir):
        cmd_prepare(argparse.Namespace(project=str(project), work=str(work_dir), force=False))
    else:
        log(f"Run: reusing prepared work dir {work_dir}")

    if not args.skip_glossary:
        cmd_glossary(
            argparse.Namespace(
                work=str(work_dir),
                out=str(work_dir / ENGLISH_GLOSSARY_NAME),
                api_key=args.translation_api_key,
                base_url=args.translation_base_url,
                model=args.translation_model,
                requirement=args.requirement,
                max_terms=args.glossary_max_terms,
                max_candidates=args.glossary_max_candidates,
                timeout_seconds=args.translate_timeout_seconds,
                max_retries=args.max_retries,
            )
        )

    cmd_translate(
        argparse.Namespace(
            work=str(work_dir),
            out=str(work_dir / CHINESE_TRANSLATIONS_NAME),
            api_key=args.translation_api_key,
            base_url=args.translation_base_url,
            model=args.translation_model,
            requirement=args.requirement,
            glossary=str(work_dir / ENGLISH_GLOSSARY_NAME) if not args.skip_glossary else "",
            timeout_seconds=args.translate_timeout_seconds,
            max_retries=args.max_retries,
            workers=args.workers,
            retry_untranslated=args.retry_untranslated,
            limit=0,
            force=args.force_translate,
        )
    )
    translations_for_apply = work_dir / CHINESE_TRANSLATIONS_NAME
    if not args.skip_consistency_review and not args.skip_glossary:
        cmd_review_consistency(
            argparse.Namespace(
                work=str(work_dir),
                translations=str(work_dir / CHINESE_TRANSLATIONS_NAME),
                out=str(work_dir / CHINESE_REVIEWED_TRANSLATIONS_NAME),
                report=str(work_dir / CHINESE_CONSISTENCY_REPORT_NAME),
                glossary=str(work_dir / ENGLISH_GLOSSARY_NAME),
                api_key=args.translation_api_key,
                base_url=args.translation_base_url,
                model=args.translation_model,
                requirement=args.requirement,
                timeout_seconds=args.translate_timeout_seconds,
                max_retries=args.max_retries,
                workers=args.workers,
            )
        )
        translations_for_apply = work_dir / CHINESE_REVIEWED_TRANSLATIONS_NAME
    cmd_apply(argparse.Namespace(work=str(work_dir), translations=str(translations_for_apply)))
    quality_json, quality_md, quality_issue_count, quality_blockers = write_quality_report_with_repair(
        work_dir,
        translations_for_apply,
    )
    log_path_hint("Quality report JSON", quality_json)
    log_path_hint("Quality report Markdown", quality_md)
    summary_path = output_dir / "run_summary.json"
    write_run_summary(
        summary_path,
        status="compile_pending",
        method=method,
        source=source,
        project=project,
        work=work_dir,
        pdf=None,
        english_tex=None,
        tex=None,
        quality_report_json=quality_json,
        quality_report_md=quality_md,
        quality_issue_count=quality_issue_count,
        vision_pack_note="vision_pack is generated after a successful compile",
    )
    if quality_blockers:
        for issue in quality_blockers[:20]:
            location = issue.get("line") or issue.get("segment_id") or issue.get("source") or "unknown"
            print(f"quality error: {issue.get('kind')} at {location}: {issue.get('snippet', '')}", file=sys.stderr)
        write_run_summary(
            summary_path,
            status="quality_failed",
            error=f"quality check found {len(quality_blockers)} blocking issue(s); inspect {quality_md}",
            method=method,
            source=source,
            project=project,
            work=work_dir,
            pdf=None,
            english_tex=work_dir / f"{ENGLISH_MERGED_BASENAME}.tex",
            tex=work_dir / f"{CHINESE_MERGED_BASENAME}.tex",
            quality_report_json=quality_json,
            quality_report_md=quality_md,
            quality_issue_count=quality_issue_count,
            vision_pack_note="vision_pack was not generated because quality checks failed before compile",
        )
        log_path_hint("Run summary", summary_path)
        die("blocking translation quality issues remain after automatic repair")
    try:
        cmd_compile(
            argparse.Namespace(
                work=str(work_dir),
                main=CHINESE_MERGED_BASENAME,
                compiler=args.compiler,
                timeout_seconds=args.compile_timeout_seconds,
            )
        )
    except SystemExit:
        work_pdf = work_dir / f"{CHINESE_MERGED_BASENAME}.pdf"
        diagnostic_vision_pack: Path | None = None
        diagnostic_vision_note = "vision_pack was not generated because compile failed"
        if work_pdf.is_file() and source_pdf_for_pack is not None and source_pdf_for_pack.is_file():
            try:
                diagnostic_vision_pack = prepare_vision_review_pack(
                    source_pdf=source_pdf_for_pack,
                    translated_pdf=work_pdf,
                    out_dir=output_dir / "vision_pack",
                    pages_spec=args.vision_pages,
                    tex_path=work_dir / f"{CHINESE_MERGED_BASENAME}.tex",
                )
                diagnostic_vision_note = "diagnostic vision_pack was generated from the PDF produced before compile errors"
                log_path_hint("Vision review pack", diagnostic_vision_pack)
                log_path_hint("Vision review manifest", diagnostic_vision_pack / "manifest.json")
            except Exception as exc:
                diagnostic_vision_note = f"vision_pack was not generated after compile errors: {exc}"
        write_run_summary(
            summary_path,
            status="compile_failed",
            error=f"compile failed; inspect {work_dir / f'{CHINESE_MERGED_BASENAME}.log'} and repair {work_dir / f'{CHINESE_MERGED_BASENAME}.tex'}",
            method=method,
            source=source,
            project=project,
            work=work_dir,
            pdf=work_pdf if work_pdf.is_file() else None,
            english_tex=work_dir / f"{ENGLISH_MERGED_BASENAME}.tex",
            tex=work_dir / f"{CHINESE_MERGED_BASENAME}.tex",
            quality_report_json=quality_json,
            quality_report_md=quality_md,
            quality_issue_count=quality_issue_count,
            vision_pack=diagnostic_vision_pack,
            vision_pack_note=diagnostic_vision_note,
        )
        log_path_hint("Run summary", summary_path)
        raise

    cmd_apply_bilingual(argparse.Namespace(work=str(work_dir), translations=str(translations_for_apply)))
    try:
        cmd_compile(
            argparse.Namespace(
                work=str(work_dir),
                main=BILINGUAL_MERGED_BASENAME,
                compiler=args.compiler,
                timeout_seconds=args.compile_timeout_seconds,
            )
        )
    except SystemExit:
        work_pdf = work_dir / f"{CHINESE_MERGED_BASENAME}.pdf"
        bilingual_work_pdf = work_dir / f"{BILINGUAL_MERGED_BASENAME}.pdf"
        write_run_summary(
            summary_path,
            status="bilingual_compile_failed",
            error=f"bilingual compile failed; inspect {work_dir / f'{BILINGUAL_MERGED_BASENAME}.log'} and repair {work_dir / f'{BILINGUAL_MERGED_BASENAME}.tex'}",
            method=method,
            source=source,
            project=project,
            work=work_dir,
            pdf=work_pdf if work_pdf.is_file() else None,
            english_tex=work_dir / f"{ENGLISH_MERGED_BASENAME}.tex",
            tex=work_dir / f"{CHINESE_MERGED_BASENAME}.tex",
            bilingual_pdf=bilingual_work_pdf if bilingual_work_pdf.is_file() else None,
            bilingual_tex=work_dir / f"{BILINGUAL_MERGED_BASENAME}.tex",
            quality_report_json=quality_json,
            quality_report_md=quality_md,
            quality_issue_count=quality_issue_count,
            vision_pack_note="vision_pack was not generated because bilingual compile failed",
            bilingual_vision_pack_note="vision_pack_bilingual was not generated because bilingual compile failed",
        )
        log_path_hint("Run summary", summary_path)
        raise

    pdf = work_dir / f"{CHINESE_MERGED_BASENAME}.pdf"
    bilingual_pdf = work_dir / f"{BILINGUAL_MERGED_BASENAME}.pdf"
    vision_pack: Path | None = None
    bilingual_vision_pack: Path | None = None
    vision_pack_note: str | None = None
    bilingual_vision_pack_note: str | None = None
    if source_pdf_for_pack is None or not source_pdf_for_pack.is_file():
        vision_pack_note = "source PDF was not available; vision_pack was not generated"
        bilingual_vision_pack_note = "source PDF was not available; vision_pack_bilingual was not generated"
        log(f"Vision review pack: skipped ({vision_pack_note})")
    else:
        vision_pack = prepare_vision_review_pack(
            source_pdf=source_pdf_for_pack,
            translated_pdf=pdf,
            out_dir=output_dir / "vision_pack",
            pages_spec=args.vision_pages,
            tex_path=work_dir / f"{CHINESE_MERGED_BASENAME}.tex",
        )
        log_path_hint("Vision review pack", vision_pack)
        log_path_hint("Vision review manifest", vision_pack / "manifest.json")
        bilingual_vision_pack = prepare_vision_review_pack(
            source_pdf=source_pdf_for_pack,
            translated_pdf=bilingual_pdf,
            out_dir=output_dir / "vision_pack_bilingual",
            pages_spec=args.vision_pages,
            tex_path=work_dir / f"{BILINGUAL_MERGED_BASENAME}.tex",
        )
        log_path_hint("Bilingual vision review pack", bilingual_vision_pack)
        log_path_hint("Bilingual vision review manifest", bilingual_vision_pack / "manifest.json")
    artifact_base = output_artifact_base_for_run(source=source, project=project, source_pdf=source_pdf_for_pack)
    exported = export_named_outputs(output_dir, work_dir, artifact_base)
    write_run_summary(
        summary_path,
        method=method,
        source=source,
        project=project,
        work=work_dir,
        pdf=exported["pdf"],
        english_tex=exported["english_tex"],
        tex=exported["tex"],
        bilingual_pdf=exported["bilingual_pdf"],
        bilingual_tex=exported["bilingual_tex"],
        quality_report_json=quality_json,
        quality_report_md=quality_md,
        quality_issue_count=quality_issue_count,
        vision_pack=vision_pack,
        bilingual_vision_pack=bilingual_vision_pack,
        vision_pack_note=vision_pack_note,
        bilingual_vision_pack_note=bilingual_vision_pack_note,
    )
    log_path_hint("Run summary", summary_path)
    log_path_hint("English TeX", exported["english_tex"])
    log_path_hint("Chinese TeX", exported["tex"])
    log_path_hint("Chinese PDF", exported["pdf"])
    log_path_hint("Bilingual TeX", exported["bilingual_tex"])
    log_path_hint("Bilingual PDF", exported["bilingual_pdf"])
    print(exported["pdf"])

def cmd_quality_check(args: argparse.Namespace) -> None:
    work = Path(args.work).resolve()
    translations = Path(args.translations).resolve() if args.translations else None
    json_path, md_path, issue_count = write_quality_report(work, translations)
    log(f"Quality issues: {issue_count}")
    log_path_hint("Quality report JSON", json_path)
    log_path_hint("Quality report Markdown", md_path)
    print(json_path)


def cmd_check_config(args: argparse.Namespace) -> None:
    candidates = resolve_dotenv_candidates(getattr(args, "env_file", None))
    loaded = [path for path in candidates if path.is_file()]
    log("Env files checked:")
    for path in candidates:
        suffix = " (loaded)" if path in loaded else ""
        log(f"  {path}{suffix}")
    if not loaded:
        log("  no .env file was found; CLI flags or process environment variables may still provide config")

    translation_status = translation_config_status(
        api_key=args.translation_api_key,
        base_url=args.translation_base_url,
        model=args.translation_model,
    )
    log("Translation API config:")
    for key, present in translation_status.items():
        log(f"  {key}: {'configured' if present else 'missing'}")

    doc2x_present = config_present(effective_doc2x_api_key(args.doc2x_api_key))
    log("DOC2X config:")
    log(f"  {DOC2X_API_KEY_ENV}: {'configured' if doc2x_present else 'missing'}")

    problems: list[str] = []
    missing_translation = [key for key, present in translation_status.items() if not present]
    if missing_translation:
        problems.append(translation_config_help(missing_translation))
    if not doc2x_present:
        problems.append(doc2x_config_help())
    if problems:
        die("\n".join(problems))
    log("Config OK")


def cmd_paths(_: argparse.Namespace) -> None:
    log_path_hint("Skill home", skill_home_dir())
    log_path_hint("Task output root", skill_output_dir())
    log_path_hint("Task tmp root", skill_tmp_dir())
    print(skill_output_dir())

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="PDF -> LaTeX -> Chinese PDF pipeline helper")
    parser.add_argument("--env-file", help="load secrets from a specific .env file before parsing subcommands")
    sub = parser.add_subparsers(dest="command", required=True)

    convert = sub.add_parser("convert", help="convert a PDF to a TeX project with DOC2X, Mathpix, or a low-fidelity text fallback")
    convert.add_argument("--pdf")
    convert.add_argument("--url", help="Remote PDF URL; the file will be downloaded locally before conversion")
    convert.add_argument("--out", required=True)
    convert.add_argument("--method", choices=["doc2x", "mathpix", "text"], default="doc2x")
    convert.add_argument("--api-key")
    convert.add_argument("--doc2x-model", choices=["v2", "v3-2026"], default="v2")
    convert.add_argument("--mathpix-app-id")
    convert.add_argument("--mathpix-app-key")
    convert.set_defaults(func=cmd_convert)

    prepare = sub.add_parser("prepare", help="copy, merge, add Chinese support, and segment a TeX project")
    prepare.add_argument("--project", required=True)
    prepare.add_argument("--work", required=True)
    prepare.add_argument("--force", action="store_true")
    prepare.set_defaults(func=cmd_prepare)

    prompts = sub.add_parser("prompts", help="export translation prompts JSONL")
    prompts.add_argument("--work", required=True)
    prompts.add_argument("--out", required=True)
    prompts.add_argument("--requirement", default="")
    prompts.set_defaults(func=cmd_prompts)

    glossary_cmd = sub.add_parser("build-glossary", help="build an article-level glossary from segments.jsonl")
    glossary_cmd.add_argument("--work", required=True)
    glossary_cmd.add_argument("--out", help=f"default: <work>/{ENGLISH_GLOSSARY_NAME}")
    glossary_cmd.add_argument("--api-key", help="translation API key; prefer PDF2ZH_TRANSLATION_API_KEY in .env")
    glossary_cmd.add_argument("--base-url", help="OpenAI-compatible chat completions base URL; prefer PDF2ZH_TRANSLATION_BASE_URL in .env")
    glossary_cmd.add_argument("--model", help="translation model name; prefer PDF2ZH_TRANSLATION_MODEL in .env")
    glossary_cmd.add_argument("--requirement", default="")
    glossary_cmd.add_argument("--max-terms", type=int, default=40)
    glossary_cmd.add_argument("--max-candidates", type=int, default=80)
    glossary_cmd.add_argument("--timeout-seconds", type=int, default=120)
    glossary_cmd.add_argument("--max-retries", type=int, default=8)
    glossary_cmd.set_defaults(func=cmd_glossary)

    translate = sub.add_parser("translate", help="translate segments.jsonl with an OpenAI-compatible chat completions API")
    translate.add_argument("--work", required=True)
    translate.add_argument("--out", help=f"default: <work>/{CHINESE_TRANSLATIONS_NAME}")
    translate.add_argument("--api-key", help="translation API key; prefer PDF2ZH_TRANSLATION_API_KEY in .env")
    translate.add_argument("--base-url", help="OpenAI-compatible chat completions base URL; prefer PDF2ZH_TRANSLATION_BASE_URL in .env")
    translate.add_argument("--model", help="translation model name; prefer PDF2ZH_TRANSLATION_MODEL in .env")
    translate.add_argument("--requirement", default="")
    translate.add_argument("--glossary", help=f"default: <work>/{ENGLISH_GLOSSARY_NAME}")
    translate.add_argument("--timeout-seconds", type=int, default=120)
    translate.add_argument("--max-retries", type=int, default=8)
    translate.add_argument("--workers", type=int, default=50, help="number of concurrent translation requests")
    translate.add_argument("--retry-untranslated", type=int, default=4, help="retry segments that still look mostly untranslated")
    translate.add_argument("--limit", type=int, default=0, help="translate at most this many new segments; useful for smoke tests")
    translate.add_argument("--force", action="store_true", help="ignore existing translations and overwrite from the start")
    translate.set_defaults(func=cmd_translate)

    review_cmd = sub.add_parser("review-consistency", help="revise translations for article-level terminology consistency")
    review_cmd.add_argument("--work", required=True)
    review_cmd.add_argument("--translations", required=True)
    review_cmd.add_argument("--out", help=f"default: <work>/{CHINESE_REVIEWED_TRANSLATIONS_NAME}")
    review_cmd.add_argument("--report", help=f"default: <work>/{CHINESE_CONSISTENCY_REPORT_NAME}")
    review_cmd.add_argument("--glossary", help=f"default: <work>/{ENGLISH_GLOSSARY_NAME}")
    review_cmd.add_argument("--api-key", help="translation API key; prefer PDF2ZH_TRANSLATION_API_KEY in .env")
    review_cmd.add_argument("--base-url", help="OpenAI-compatible chat completions base URL; prefer PDF2ZH_TRANSLATION_BASE_URL in .env")
    review_cmd.add_argument("--model", help="translation model name; prefer PDF2ZH_TRANSLATION_MODEL in .env")
    review_cmd.add_argument("--requirement", default="")
    review_cmd.add_argument("--timeout-seconds", type=int, default=120)
    review_cmd.add_argument("--max-retries", type=int, default=8)
    review_cmd.add_argument("--workers", type=int, default=50)
    review_cmd.set_defaults(func=cmd_review_consistency)

    vision_pack_cmd = sub.add_parser("prepare-vision-pack", help="render source and translated PDF pages for vision-assisted layout rebuilding")
    vision_pack_cmd.add_argument("--source-pdf", required=True)
    vision_pack_cmd.add_argument("--translated-pdf", required=True)
    vision_pack_cmd.add_argument("--out", required=True)
    vision_pack_cmd.add_argument("--pages", default="1-3")
    vision_pack_cmd.add_argument("--tex", help="optional translated TeX path for later patching")
    vision_pack_cmd.set_defaults(func=cmd_prepare_vision_pack)

    quality_cmd = sub.add_parser("quality-check", help="write machine-detectable translation quality review reports")
    quality_cmd.add_argument("--work", required=True)
    quality_cmd.add_argument("--translations", help=f"default: <work>/{CHINESE_REVIEWED_TRANSLATIONS_NAME}")
    quality_cmd.set_defaults(func=cmd_quality_check)

    check_config_cmd = sub.add_parser("check-config", help="check .env/API configuration without printing secret values")
    check_config_cmd.add_argument("--translation-api-key", help="translation API key; prefer PDF2ZH_TRANSLATION_API_KEY in .env")
    check_config_cmd.add_argument("--translation-base-url", help="OpenAI-compatible chat completions base URL; prefer PDF2ZH_TRANSLATION_BASE_URL in .env")
    check_config_cmd.add_argument("--translation-model", help="translation model name; prefer PDF2ZH_TRANSLATION_MODEL in .env")
    check_config_cmd.add_argument("--doc2x-api-key", help="DOC2X API key; prefer DOC2X_API_KEY in .env")
    check_config_cmd.set_defaults(func=cmd_check_config)

    apply = sub.add_parser("apply", help=f"apply translations JSONL and write {CHINESE_MERGED_BASENAME}.tex")
    apply.add_argument("--work", required=True)
    apply.add_argument("--translations", required=True)
    apply.set_defaults(func=cmd_apply)

    apply_bilingual = sub.add_parser("apply-bilingual", help=f"apply translations JSONL and write {BILINGUAL_MERGED_BASENAME}.tex")
    apply_bilingual.add_argument("--work", required=True)
    apply_bilingual.add_argument("--translations", required=True)
    apply_bilingual.set_defaults(func=cmd_apply_bilingual)

    compile_cmd = sub.add_parser("compile", help=f"compile {CHINESE_MERGED_BASENAME}.tex")
    compile_cmd.add_argument("--work", required=True)
    compile_cmd.add_argument("--main", default=CHINESE_MERGED_BASENAME)
    compile_cmd.add_argument("--compiler", choices=["lualatex", "xelatex", "pdflatex"])
    compile_cmd.add_argument("--timeout-seconds", type=int, default=180)
    compile_cmd.set_defaults(func=cmd_compile)

    run_cmd = sub.add_parser("run", help="run the whole PDF/project -> Chinese PDF pipeline")
    run_cmd.add_argument("--pdf")
    run_cmd.add_argument("--url", help="Remote PDF URL; the file will be downloaded locally before conversion")
    run_cmd.add_argument("--project", help="Existing TeX project; skips conversion")
    run_cmd.add_argument("--source-pdf", help="Original source PDF path; used to generate the visual review pack when using --project")
    run_cmd.add_argument("--output-dir", help="default: create a fresh task folder under PDF2ZH_SKILL_OUTPUT_DIR or PDF2ZH_SKILL_HOME/runs")
    run_cmd.add_argument("--method", choices=["auto", "doc2x", "mathpix", "text"], default="auto")
    run_cmd.add_argument("--vision-pages", default="1-3", help="page spec for vision compare pack, e.g. 1-3,5")
    run_cmd.add_argument("--translation-api-key", help="translation API key; prefer PDF2ZH_TRANSLATION_API_KEY in .env")
    run_cmd.add_argument("--translation-base-url", help="OpenAI-compatible chat completions base URL; prefer PDF2ZH_TRANSLATION_BASE_URL in .env")
    run_cmd.add_argument("--translation-model", help="translation model name; prefer PDF2ZH_TRANSLATION_MODEL in .env")
    run_cmd.add_argument("--doc2x-api-key", help="DOC2X API key; prefer DOC2X_API_KEY in .env")
    run_cmd.add_argument("--doc2x-model", choices=["v2", "v3-2026"], default="v2")
    run_cmd.add_argument("--mathpix-app-id")
    run_cmd.add_argument("--mathpix-app-key")
    run_cmd.add_argument("--requirement", default="")
    run_cmd.add_argument("--workers", type=int, default=50)
    run_cmd.add_argument("--glossary-max-terms", type=int, default=40)
    run_cmd.add_argument("--glossary-max-candidates", type=int, default=80)
    run_cmd.add_argument("--retry-untranslated", type=int, default=4)
    run_cmd.add_argument("--max-retries", type=int, default=8)
    run_cmd.add_argument("--translate-timeout-seconds", type=int, default=120)
    run_cmd.add_argument("--compile-timeout-seconds", type=int, default=300)
    run_cmd.add_argument("--compiler", choices=["lualatex", "xelatex", "pdflatex"])
    run_cmd.add_argument("--skip-glossary", action="store_true")
    run_cmd.add_argument("--skip-consistency-review", action="store_true")
    run_cmd.add_argument("--force-convert", action="store_true")
    run_cmd.add_argument("--force-prepare", action="store_true")
    run_cmd.add_argument("--force-translate", action="store_true")
    run_cmd.set_defaults(func=cmd_run)

    paths_cmd = sub.add_parser("paths", help="show resolved runtime, output, and tmp directories")
    paths_cmd.set_defaults(func=cmd_paths)
    return parser

def main(argv: list[str] | None = None) -> int:
    load_dotenv_candidates(extract_env_file_arg(argv))
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "env_file", None):
        load_dotenv_candidates(args.env_file)
    args.func(args)
    return 0
