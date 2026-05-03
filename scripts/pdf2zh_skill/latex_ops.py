from __future__ import annotations

from .common import *

def rm_comments(text: str) -> str:
    lines = []
    for line in text.splitlines():
        if line.lstrip().startswith("%"):
            continue
        lines.append(re.sub(r"(?<!\\)%.*", "", line))
    return "\n".join(lines) + "\n"

def find_main_tex(project: Path) -> Path:
    candidates: list[Path] = []
    for path in project.rglob("*.tex"):
        if path.name.startswith("merge"):
            continue
        content = path.read_text(encoding="utf-8", errors="ignore")
        if r"\documentclass" in content:
            candidates.append(path)
    if not candidates:
        die(f"no main .tex file with \\documentclass found under {project}")
    if len(candidates) == 1:
        return candidates[0]

    unexpected = ["\\LaTeX", "manuscript", "Guidelines", "font", "citations", "rejected", "blind review", "reviewers"]
    expected = ["\\input", "\\include", "\\ref", "\\cite"]
    scored = []
    for path in candidates:
        content = rm_comments(path.read_text(encoding="utf-8", errors="ignore"))
        score = sum(word in content for word in expected) - sum(word in content for word in unexpected)
        scored.append((score, len(content), path))
    scored.sort(reverse=True)
    return scored[0][2]

def find_tex_include(base: Path, name: str) -> Path | None:
    raw = (base / name).with_suffix(".tex") if not name.lower().endswith(".tex") else base / name
    if raw.is_file():
        return raw
    target_name = raw.name.lower()
    for item in base.glob("*.tex"):
        if item.name.lower() == target_name:
            return item
    return None

def merge_tex(project: Path, tex_path: Path, seen: set[Path] | None = None) -> str:
    seen = seen or set()
    tex_path = tex_path.resolve()
    if tex_path in seen:
        return ""
    seen.add(tex_path)
    content = rm_comments(tex_path.read_text(encoding="utf-8", errors="replace"))

    pattern = re.compile(r"\\(?:input|include)\{([^}]+)\}")
    pieces: list[str] = []
    pos = 0
    for match in pattern.finditer(content):
        pieces.append(content[pos : match.start()])
        include = find_tex_include(tex_path.parent, match.group(1)) or find_tex_include(project, match.group(1))
        if include is None:
            pieces.append(f"\n% missing include: {match.group(0)}\n")
        else:
            pieces.append(merge_tex(project, include, seen))
        pos = match.end()
    pieces.append(content[pos:])
    return "".join(pieces)

def inject_chinese_support(text: str) -> str:
    if r"\usepackage{ctex}" not in text and r"\usepackage[UTF8]{ctex}" not in text and r"\usepackage{xeCJK}" not in text:
        text = re.sub(r"(\\documentclass(?:\[[^\]]*\])?\{[^}]+\}\s*)", r"\1\\usepackage[UTF8]{ctex}\n", text, count=1)
    if r"\usepackage{url}" not in text and r"\url{" in text:
        text = re.sub(r"(\\documentclass(?:\[[^\]]*\])?\{[^}]+\}\s*)", r"\1\\usepackage{url}\n", text, count=1)
    return text

def normalize_problem_unicode(text: str) -> str:
    """Normalize OCR compatibility glyphs that commonly break CJK LaTeX fonts."""
    replacements = {
        "→": r"\ensuremath{\rightarrow}",
        "←": r"\ensuremath{\leftarrow}",
        "⇒": r"\ensuremath{\Rightarrow}",
        "⇐": r"\ensuremath{\Leftarrow}",
    }
    chars: list[str] = []
    for ch in text:
        if ch in replacements:
            chars.append(replacements[ch])
            continue
        code = ord(ch)
        if ch in "\n\r\t":
            chars.append(ch)
        elif code < 32 or 0x7F <= code <= 0x9F:
            continue
        elif ch == "｜":
            chars.append("|")
        elif ch in CJK_RADICAL_MAP:
            chars.append(CJK_RADICAL_MAP[ch])
        elif 0x2F00 <= code <= 0x2FDF:
            chars.append(unicodedata.normalize("NFKC", ch))
        else:
            chars.append(ch)
    return "".join(chars)

def sanitize_latex_source(text: str) -> str:
    text = normalize_problem_unicode(text)
    # arXiv sources often include pdfTeX-only directives. They break the
    # LuaLaTeX/XeLaTeX path used for Chinese output and are unnecessary here.
    text = re.sub(r"(?m)^[ \t]*\\pdfoutput[ \t]*=[ \t]*1[ \t]*(?:%.*)?\n?", "", text, count=1)
    # Some PDF-to-TeX converters emit XeTeX-only font helpers. This skill
    # prefers LuaLaTeX for CJK robustness, so keep language handling in ctex.
    text = re.sub(r"^[ \t]*\\usepackage(?:\[[^\]]*\])?\{ucharclasses\}[ \t]*\n", "", text, flags=re.M)
    text = normalize_xcolor_package_loads(text)
    text = normalize_linebreak_dimension_commands(text)
    text = normalize_section_reference_phrases(text)
    text = normalize_double_escaped_reference_commands(text)
    text = drop_visual_demo_ocr_blocks(text)
    text = normalize_reference_heading(text)
    text = normalize_caption_prefixes(text)
    text = strip_markdown_emphasis_artifacts(text)
    text = normalize_reference_command_arguments(text)
    text = normalize_font_fallback_blocks(text)
    text = normalize_text_symbol_commands(text)
    text = normalize_math_font_fragments(text)
    text = normalize_visual_primitive_token_names(text)
    text = normalize_item_syntax(text)
    text = normalize_reference_item_brackets(text)
    text = normalize_pandoc_longtable_groups(text)
    text = wrap_pandoc_figure_blocks(text)
    text = escape_unescaped_text_underscores(text)
    text = normalize_reference_command_arguments(text)
    return text

def normalize_frontmatter_content(text: str) -> str:
    replacements = {
        "*: Core contributors ‡: Project lead": "*: 核心贡献者 ‡: 项目负责人",
        "*: Core contributors  ‡: Project lead": "*: 核心贡献者 ‡: 项目负责人",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    return text

def normalize_frontmatter_layout(text: str) -> str:
    pattern = re.compile(
        r"(\\begin\{document\}\s*)(\\section\*\{([^}]*)\}\s*)(.*?)(\\section\*\{(Abstract|摘要)\}\s*)",
        re.S,
    )
    match = pattern.search(text)
    if not match:
        return text

    begin_doc, _title_heading, title, author_block, _abstract_heading, abstract_label = match.groups()
    if r"\section" in author_block or len(author_block) > 5000:
        return text

    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", author_block) if part.strip()]
    if not paragraphs:
        return text

    title_text = compact_whitespace(title)
    if not title_text:
        return text

    centered_paragraphs = "\n\n".join(paragraph + r"\par" for paragraph in paragraphs)
    abstract_title = "摘要" if abstract_label == "摘要" else abstract_label
    replacement = (
        begin_doc
        + r"\vspace*{1em}" + "\n"
        + r"\noindent\hfill\rule{0.86\linewidth}{0.2mm}\hfill" + "\n\n"
        + r"\begin{center}" + "\n"
        + r"{\LARGE\bfseries " + title_text + r"\par}" + "\n"
        + r"\vspace{1.5em}" + "\n"
        + centered_paragraphs + "\n"
        + r"\end{center}" + "\n\n"
        + r"\begin{center}" + "\n"
        + r"{\Large\bfseries " + abstract_title + r"\par}" + "\n"
        + r"\end{center}" + "\n\n"
    )
    return text[: match.start()] + replacement + text[match.end() :]

def normalize_item_syntax(text: str) -> str:
    # Some translation models occasionally emit list items without whitespace
    # between \\item and the following text (e.g. "\\itemfoo"), which becomes
    # a single undefined control sequence. Add a space so LaTeX parses
    # "\item" correctly.
    return re.sub(r"\\item(?=\S)", r"\\item ", text)


def normalize_linebreak_dimension_commands(text: str) -> str:
    # Translation models sometimes turn "\\[2pt]" into "\[2pt]", which LaTeX
    # interprets as display-math start instead of a linebreak with extra space.
    return re.sub(
        r"(?<!\\)\\\[(\s*\d+(?:\.\d+)?(?:pt|em|ex|mm|cm|in)\s*)\]",
        r"\\\\[\1]",
        text,
    )


def normalize_section_reference_phrases(text: str) -> str:
    return re.sub(
        r"\\S所示[。.]?\s*\\ref\{([^}]+)\}",
        r"\\S\\ref{\1}所示",
        text,
    )


def normalize_double_escaped_reference_commands(text: str) -> str:
    commands = r"(?:Cref|cref|ref|eqref|pageref|nameref|cite|citep|citet|citealp|citealt|citeauthor|citeyear)"
    return re.sub(rf"\\\\({commands})\{{", r"\\\1{", text)


def normalize_xcolor_package_loads(text: str) -> str:
    pattern = re.compile(r"^[ \t]*\\usepackage(?:\[([^\]]*)\])?\{xcolor\}[ \t]*\n?", re.M)
    matches = list(pattern.finditer(text))
    if not matches:
        return text

    options: list[str] = []
    seen: set[str] = set()
    for match in matches:
        raw_options = match.group(1) or ""
        for option in (part.strip() for part in raw_options.split(",")):
            if option and option not in seen:
                options.append(option)
                seen.add(option)
    load = "\\usepackage"
    if options:
        load += "[" + ",".join(options) + "]"
    load += "{xcolor}\n"

    pieces: list[str] = []
    cursor = 0
    for match in matches:
        pieces.append(text[cursor : match.start()])
        cursor = match.end()
    pieces.append(text[cursor:])
    text = "".join(pieces)

    docclass = re.search(r"\\documentclass(?:\[[^\]]*\])?\{[^}]+\}\s*", text)
    if not docclass:
        return load + text
    return text[: docclass.end()] + "\n" + load + text[docclass.end() :]


def strip_markdown_emphasis_artifacts(text: str) -> str:
    # Chat models sometimes emit Markdown emphasis inside LaTeX text. In TeX
    # those markers are printed literally, so remove only balanced delimiters
    # and keep the translated prose.
    text = re.sub(r"(?<!\\)\*\*([^\n*][^\n]*?[^\n*])(?<!\\)\*\*", r"\1", text)
    text = re.sub(r"(?<!\\)__([^\n_][^\n]*?[^\n_])(?<!\\)__", r"\1", text)
    text = re.sub(r"(?<!`)`([^`\n]+)`(?!`)", r"\1", text)
    return text


def looks_like_visual_demo_ocr_block(text: str) -> bool:
    stripped = compact_whitespace(text)
    if len(stripped) < 80:
        return False
    signals = 0
    if "Trigger\\_Placeholder" in text or "Trigger Placeholder" in text:
        signals += 2
    point_hits = len(re.findall(r"(?:<\s*\|\s*/?\s*point\s*\|>|\\text\{\s*/?\s*point\s*\}|/point)", text, re.I))
    if point_hits >= 3:
        signals += 1
    coord_hits = len(re.findall(r"\d{2,4}\s*,\s*\d{2,4}", text))
    coord_hits += len(re.findall(r"\{\d{2,4}\}\s*,\s*\{\d{2,4}\}", text))
    coord_hits += len(re.findall(r"\[\d{2,4}\s*,\s*\d{2,4}\]", text))
    if coord_hits >= 6:
        signals += 1
    step_hits = len(re.findall(r"\bStep\d*\b|\bStart Exploring\b|\bResponse\b|\\boxed|boxed\\\{", text))
    if step_hits >= 1 and point_hits >= 2 and len(stripped) >= 100:
        return True
    if step_hits >= 2:
        signals += 1
    if len(stripped) > 220 and point_hits >= 2 and coord_hits >= 4:
        signals += 1
    return signals >= 2


def drop_visual_demo_ocr_blocks(text: str) -> str:
    parts = re.split(r"(\n\s*\n)", text)
    dropped = [False] * len(parts)

    def is_separator(index: int) -> bool:
        return bool(re.fullmatch(r"\n\s*\n", parts[index]))

    def neighbor_content(index: int, direction: int) -> int | None:
        cursor = index + direction
        while 0 <= cursor < len(parts):
            if not is_separator(cursor):
                return cursor
            cursor += direction
        return None

    for index, part in enumerate(parts):
        if is_separator(index):
            continue
        if looks_like_visual_demo_ocr_block(part):
            dropped[index] = True

    for index, part in enumerate(parts):
        if is_separator(index) or dropped[index]:
            continue
        stripped = compact_whitespace(part)
        letters = sum("A" <= ch <= "Z" or "a" <= ch <= "z" for ch in stripped)
        cjk = sum("\u4e00" <= ch <= "\u9fff" for ch in stripped)
        prev_index = neighbor_content(index, -1)
        next_index = neighbor_content(index, 1)
        adjacent_to_dropped = (
            (prev_index is not None and dropped[prev_index])
            or (next_index is not None and dropped[next_index])
        )
        if not adjacent_to_dropped:
            continue
        if stripped == "Thinking with Visual Primitives":
            dropped[index] = True
            continue
        if cjk == 0 and letters >= 12 and len(stripped) <= 120:
            dropped[index] = True

    kept = [part for index, part in enumerate(parts) if not dropped[index]]
    return re.sub(r"\n{4,}", "\n\n", "".join(kept))


def normalize_reference_heading(text: str) -> str:
    first_ref = re.search(r"(?m)^\{\[\}1\{\]\}", text)
    if not first_ref:
        return text

    prefix = text[: first_ref.start()]
    suffix = text[first_ref.start() :]
    prefix = re.sub(r"(?:References|参考文献)\s*", "\n\n", prefix, count=1)
    if r"\section*{参考文献}" not in prefix:
        prefix = prefix.rstrip() + "\n\n\\section*{参考文献}\n\n"
    return prefix + suffix.lstrip()


def normalize_caption_prefixes(text: str) -> str:
    text = re.sub(r"(?m)^Figure\s+(\d+)\s*\|", r"图\1 |", text)
    text = re.sub(r"(?m)^Table\s+(\d+)\s*\|", r"表\1 |", text)
    return text


REF_LIKE_COMMANDS = (
    "Cref|cref|Crefrange|crefrange|autoref|Autoref|ref|eqref|pageref|nameref|"
    "cite|cites|citep|citet|citealp|citealt|citeauthor|citeyear|label"
)


def ref_like_command_pattern() -> str:
    return rf"\\(?:{REF_LIKE_COMMANDS})\*?(?:\[[^\]]*\])*" + r"\{[^{}]*\}"


def normalize_reference_command_arguments(text: str) -> str:
    # Label, reference and citation keys are LaTeX identifiers. Underscores are
    # valid there and must not be escaped as text underscores.
    pattern = re.compile(
        rf"(\\(?:{REF_LIKE_COMMANDS})\*?(?:\[[^\]]*\])*)"
        r"\{([^{}]*)\}"
    )

    def repl(match: re.Match) -> str:
        return match.group(1) + "{" + match.group(2).replace(r"\_", "_") + "}"

    return pattern.sub(repl, text)

def normalize_text_symbol_commands(text: str) -> str:
    return re.sub(r"\\(textless|textgreater|textbar)(?!\{\})", r"\\\1{}", text)

def escape_unescaped_text_underscores(text: str) -> str:
    spans = protected_spans(text)
    pieces: list[str] = []
    cursor = 0
    for start, end in spans:
        if cursor < start:
            pieces.append(escape_underscores_outside_inline_math(text[cursor:start]))
        pieces.append(text[start:end])
        cursor = end
    if cursor < len(text):
        pieces.append(escape_underscores_outside_inline_math(text[cursor:]))
    return "".join(pieces)

def escape_underscores_outside_inline_math(text: str) -> str:
    out: list[str] = []
    i = 0
    math_delim: str | None = None
    while i < len(text):
        if text.startswith(r"\(", i):
            math_delim = r"\)"
            out.append(r"\(")
            i += 2
            continue
        if text.startswith(r"\[", i):
            math_delim = r"\]"
            out.append(r"\[")
            i += 2
            continue
        if math_delim and text.startswith(math_delim, i):
            out.append(math_delim)
            i += len(math_delim)
            math_delim = None
            continue
        if text.startswith("$$", i):
            math_delim = None if math_delim == "$$" else "$$"
            out.append("$$")
            i += 2
            continue
        if text[i] == "$":
            math_delim = None if math_delim == "$" else "$"
            out.append(text[i])
            i += 1
            continue
        if text[i] == "_" and math_delim is None and (i == 0 or text[i - 1] != "\\"):
            out.append(r"\_")
        else:
            out.append(text[i])
        i += 1
    return "".join(out)

def normalize_math_font_fragments(text: str) -> str:
    # OCR converters can wrap accented math symbols in \mathbf; LuaTeX may then
    # emit missing-glyph errors for the accent slot even though the PDF exists.
    return re.sub(
        r"\\mathbf\s*\{\s*(\\(?:bar|hat|tilde|vec|dot|ddot)\s*\{\s*[^{}]+?\s*\})\s*\}",
        r"\1",
        text,
    )

def normalize_font_fallback_blocks(text: str) -> str:
    start = 0
    needle = r"\IfFontExistsTF{Source Han Serif CN}"
    replacement = r"% pdf2zh-skill: CJK font fallback is handled by ctex"
    while True:
        pos = text.find(needle, start)
        if pos < 0:
            return text
        end = consume_latex_command_with_braced_args(text, pos, 3)
        if end is None:
            start = pos + len(needle)
            continue
        text = text[:pos] + replacement + text[end:]
        start = pos + len(replacement)

def consume_latex_command_with_braced_args(text: str, start: int, arg_count: int) -> int | None:
    match = re.match(r"\\[A-Za-z]+\*?", text[start:])
    if not match:
        return None
    cursor = start + len(match.group(0))
    for _ in range(arg_count):
        while cursor < len(text) and text[cursor].isspace():
            cursor += 1
        if cursor >= len(text) or text[cursor] != "{":
            return None
        end = matching_brace(text, cursor)
        if end is None:
            return None
        cursor = end + 1
    return cursor

def normalize_visual_primitive_token_names(text: str) -> str:
    replacements = {
        "参考": "ref",
        "盒子": "box",
        "框": "box",
        "点": "point",
    }

    for cn, en in replacements.items():
        text = re.sub(rf"\|\s*/\s*{cn}", f"|/{en}", text)
        text = re.sub(rf"\|\s*{cn}", f"|{en}", text)
        text = re.sub(rf"/\s*{cn}\s*\|", f"/{en}|", text)
        text = re.sub(rf"{cn}\s*\|", f"{en}|", text)

    def replace_between_bars(match: re.Match) -> str:
        raw = match.group(1).strip()
        slash = "/" if raw.startswith("/") else ""
        name = raw[1:].strip() if slash else raw
        return "|" + slash + replacements.get(name, name) + "|"

    text = re.sub(r"\|\s*(/?.{1,4}?)\s*\|", replace_between_bars, text)
    return text

def normalize_reference_item_brackets(text: str) -> str:
    text = re.sub(
        r"(\\section\{[^}]*参考文献[^}]*\}\\label\{references\})\[(\d{1,3})\]",
        r"\1\n{[}\2{]}",
        text,
    )
    text = re.sub(r"(?m)^(\s*)\[(\d{1,3})\]", r"\1{[}\2{]}", text)
    return text

def normalize_pandoc_longtable_groups(text: str) -> str:
    if r"{\def\LTcaptype" not in text:
        return text
    return re.sub(r"(\\end\{longtable\})(?!\s*\})", r"\1\n}", text)

def wrap_pandoc_figure_blocks(text: str) -> str:
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    i = 0

    def is_image_line(line: str) -> bool:
        return r"\pandocbounded{\includegraphics" in line

    def is_figure_caption_line(line: str) -> bool:
        stripped = line.strip()
        return stripped.startswith("Figure ") or stripped.startswith("图")

    while i < len(lines):
        if not is_image_line(lines[i]):
            out.append(lines[i])
            i += 1
            continue

        start = i
        j = i
        saw_caption = False
        while j < len(lines):
            stripped = lines[j].strip()
            if is_figure_caption_line(lines[j]):
                saw_caption = True
            elif saw_caption and not stripped:
                break
            elif saw_caption and stripped.startswith("\\section"):
                break
            elif saw_caption and stripped.startswith("\\subsection"):
                break
            elif saw_caption and stripped.startswith("\\subsubsection"):
                break
            elif saw_caption and is_image_line(lines[j]):
                break
            j += 1
        block_lines = lines[start:j]
        block_text = "".join(block_lines)

        if r"\begin{figure}" in block_text or r"\begin{figure*}" in block_text:
            out.append(block_text)
            if j < len(lines) and not lines[j].strip():
                out.append(lines[j])
                i = j + 1
            else:
                i = j
            continue

        has_caption = any(is_figure_caption_line(line) for line in block_lines)
        image_count = sum(1 for line in block_lines if is_image_line(line))
        if has_caption and image_count > 0:
            wrapped = "\\begin{figure}[tbp]\n\\centering\n" + block_text.rstrip() + "\n\\end{figure}\n"
            out.append(wrapped)
            if j < len(lines) and not lines[j].strip():
                out.append(lines[j])
                i = j + 1
            else:
                i = j
            continue

        out.append(block_text)
        if j < len(lines) and not lines[j].strip():
            out.append(lines[j])
            i = j + 1
        else:
            i = j

    return "".join(out)

def matching_brace(text: str, open_index: int) -> int | None:
    level = 0
    i = open_index
    while i < len(text):
        ch = text[i]
        if ch == "\\":
            i += 2
            continue
        if ch == "{":
            level += 1
        elif ch == "}":
            level -= 1
            if level == 0:
                return i
        i += 1
    return None

def protected_spans(text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []

    def add(pattern: str, flags: int = 0) -> None:
        for match in re.finditer(pattern, text, flags):
            spans.append(match.span())

    begin_doc = re.search(r"\\begin\{document\}", text)
    if begin_doc:
        spans.append((0, begin_doc.end()))
    else:
        maketitle = re.search(r"\\maketitle", text)
        if maketitle:
            spans.append((0, maketitle.end()))

    add(r"\\iffalse.*?\\fi", re.DOTALL)
    add(r"\$\$.*?\$\$", re.DOTALL)
    add(r"(?<!\\)\\\[.*?\\\]", re.DOTALL)
    add(r"\\begin\{center\}.*?\\end\{center\}", re.DOTALL)
    add(r"\\begin\{(?:tabular|tabular\*|tabularx|array)\}(?:\{.*?\})?.*?\\end\{(?:tabular|tabular\*|tabularx|array)\}", re.DOTALL)
    spans.extend(short_generic_environment_spans(text, limit_n_lines=42))
    add(r"\\begin\{(?:equation|equation\*|align|align\*|multline|multline\*|gather|gather\*)\}.*?\\end\{[^}]+\}", re.DOTALL)
    add(r"\\begin\{(?:figure|figure\*|table|table\*|algorithm|lstlisting|thebibliography)\}.*?\\end\{[^}]+\}", re.DOTALL)
    add(ref_like_command_pattern())
    add(r"\\(?:url|href|includegraphics|bibliography|bibliographystyle)\*?(?:\[[^\]]*\])?\{[^}]*\}")
    add(r"\\(?:begin|end)\{[^}]+\}")
    add(r"\\(?:newpage|clearpage|appendix|tableofcontents)\b")

    # Reopen abstract and captions after broad environment protection.
    reopened: list[tuple[int, int]] = []
    for pattern in [r"\\caption\{", r"\\abstract\{"]:
        for match in re.finditer(pattern, text):
            end = matching_brace(text, match.end() - 1)
            if end:
                reopened.append((match.end(), end))
    for match in re.finditer(r"\\begin\{abstract\}(.*?)\\end\{abstract\}", text, re.DOTALL):
        reopened.append(match.span(1))

    if not reopened:
        return normalize_spans(spans)

    normalized = normalize_spans(spans)
    result: list[tuple[int, int]] = []
    for start, end in normalized:
        cuts = [(max(start, a), min(end, b)) for a, b in reopened if a < end and b > start]
        if not cuts:
            result.append((start, end))
            continue
        cursor = start
        for a, b in sorted(cuts):
            if cursor < a:
                result.append((cursor, a))
            cursor = max(cursor, b)
        if cursor < end:
            result.append((cursor, end))
    return normalize_spans(result)

def short_generic_environment_spans(text: str, limit_n_lines: int) -> list[tuple[int, int]]:
    whitelist = {
        "document",
        "abstract",
        "lemma",
        "definition",
        "sproof",
        "em",
        "emph",
        "textit",
        "textbf",
        "itemize",
        "enumerate",
    }
    spans: list[tuple[int, int]] = []
    pattern = re.compile(r"\\begin\{([a-zA-Z\*]+)\}(.*?)\\end\{\1\}", re.DOTALL)
    for match in pattern.finditer(text):
        env = match.group(1)
        body = match.group(2)
        if env in whitelist:
            continue
        if body.count("\n") < limit_n_lines:
            spans.append(match.span())
    return spans

def normalize_spans(spans: Iterable[tuple[int, int]]) -> list[tuple[int, int]]:
    ordered = sorted((a, b) for a, b in spans if a < b)
    if not ordered:
        return []
    merged = [ordered[0]]
    for start, end in ordered[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))
    return merged

def mask_latex_blocks_for_translation(text: str) -> tuple[str, dict[str, str]]:
    protected: dict[str, str] = {}

    def repl(match: re.Match) -> str:
        token = f"__LATEX_BLOCK_{len(protected):04d}__"
        protected[token] = match.group(0)
        return token

    patterns = [
        r"\\\\(?:\[[^\]]*\])?",
        r"\\textless\s*\|\s*/?\s*(?:ref|box|point)\s*\|\s*\\textgreater",
        r"\|\s*/?\s*(?:ref|box|point)\s*\|\s*\\textgreater",
        r"\\textless\s*\|\s*/?\s*(?:ref|box|point)\s*\|",
        r"(?<!\\)\\\(.+?\\\)",
        r"(?<!\$)\$(?!\$).+?(?<!\$)\$(?!\$)",
        r"\\(?:def|setcounter)\b[^\n]*",
        r"\\tightlist\b",
        r"\\item\b",
        r"\\(?:textless|textbar|textgreater|ldots|par|sloppy|maketitle|noindent)\b(?:\{\})?",
        r"\\(?:begin|end)\{[^}]+\}",
        ref_like_command_pattern(),
        r"\\(?:url|href|includegraphics)\*?(?:\[[^\]]*\])?\{[^}]*\}",
    ]
    masked = text
    for pattern in patterns:
        masked = re.sub(pattern, repl, masked, flags=re.DOTALL)
    return masked, protected


def unmask_latex_blocks(text: str, protected: dict[str, str]) -> str:
    text = restore_mask_token_variants(text)
    for token, original in protected.items():
        text = text.replace(token, original)
    return text


def restore_mask_token_variants(text: str) -> str:
    return re.sub(
        r"(?:\\_|_){2}LATEX(?:\\_|_)BLOCK(?:\\_|_)\d{4}(?:\\_|_){2}",
        lambda match: match.group(0).replace(r"\_", "_"),
        text,
    )

def split_nodes(text: str) -> list[Node]:
    spans = protected_spans(text)
    raw: list[Node] = []
    cursor = 0
    for start, end in spans:
        if cursor < start:
            raw.append(Node(TRANSLATE, text[cursor:start]))
        raw.append(Node(PRESERVE, text[start:end]))
        cursor = end
    if cursor < len(text):
        raw.append(Node(TRANSLATE, text[cursor:]))

    nodes: list[Node] = []
    segment_index = 0
    for node in raw:
        if node.kind == TRANSLATE and not should_translate(node.text):
            node.kind = PRESERVE
        if node.kind == TRANSLATE:
            split_parts = split_translate_text_preserving_layout(node.text, max_chars=5000)
            for part in split_parts:
                if part.kind == TRANSLATE:
                    segment_index += 1
                    part.segment_id = f"seg-{segment_index:04d}"
                nodes.append(part)
        else:
            nodes.append(node)
    return coalesce_preserve(nodes)

def should_translate(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    if re.match(r"^\{\[\}\d+\{\]\}", stripped) or re.match(r"^\[\d+\]", stripped):
        return False
    letters = sum(ch.isalpha() for ch in stripped)
    commands = stripped.count("\\")
    has_heading = bool(re.search(r"\\(?:section|subsection|subsubsection|paragraph|subparagraph)\*?\{", stripped))
    if has_heading:
        return letters >= 3 and commands < max(20, letters)
    if len(stripped) < 40:
        return False
    return letters >= 20 and commands < max(12, letters // 3)

def paragraph_chunks(text: str, max_chars: int) -> Iterator[str]:
    parts = re.split(r"(\n\s*\n)", text)
    chunk = ""
    for part in parts:
        if len(chunk) + len(part) > max_chars and chunk:
            yield chunk
            chunk = part
        else:
            chunk += part
    if chunk:
        yield chunk

def sentence_like_chunks(text: str, max_chars: int) -> Iterator[str]:
    if len(text) <= max_chars:
        yield text
        return
    pieces = re.split(r"(?<=[\.\?!;:。！？；：])(\s+)", text)
    chunk = ""
    for piece in pieces:
        if not piece:
            continue
        if len(chunk) + len(piece) > max_chars and chunk.strip():
            yield chunk
            chunk = piece
        else:
            chunk += piece
    if chunk:
        yield chunk

def split_translate_text_preserving_layout(text: str, max_chars: int) -> list[Node]:
    nodes: list[Node] = []
    parts = re.split(r"(\n\s*\n+)", text)
    for part in parts:
        if not part:
            continue
        if re.fullmatch(r"\n\s*\n+", part, flags=re.S):
            nodes.append(Node(PRESERVE, part))
            continue

        match = re.match(r"^(\s*)(.*?)(\s*)$", part, flags=re.S)
        if not match:
            nodes.append(Node(PRESERVE, part))
            continue
        leading, body, trailing = match.groups()
        if leading:
            nodes.append(Node(PRESERVE, leading))
        if body:
            if should_translate(body):
                for chunk in sentence_like_chunks(body, max_chars=max_chars):
                    if should_translate(chunk):
                        nodes.append(Node(TRANSLATE, chunk))
                    else:
                        nodes.append(Node(PRESERVE, chunk))
            else:
                nodes.append(Node(PRESERVE, body))
        if trailing:
            nodes.append(Node(PRESERVE, trailing))
    return nodes

def coalesce_preserve(nodes: list[Node]) -> list[Node]:
    out: list[Node] = []
    for node in nodes:
        if out and out[-1].kind == PRESERVE and node.kind == PRESERVE:
            out[-1].text += node.text
        else:
            out.append(node)
    return out

def fix_translation(translated: str, original: str) -> str:
    translated = strip_markdown_emphasis_artifacts(translated)
    translated = normalize_reference_command_arguments(translated)
    translated = re.sub(r"(?<!\\)%", r"\\%", translated)
    translated = re.sub(r"\\([a-zA-Z]{2,20})\s+\{", r"\\\1{", translated)
    translated = re.sub(r"\\([a-zA-Z]{2,20})\{([^}]*)\}", normalize_command_argument_punctuation, translated)
    if "Traceback" in translated or "[Local Message]" in translated:
        return original
    if original.count(r"\begin") != translated.count(r"\begin"):
        return original
    if brace_balance(original) != brace_balance(translated):
        translated = join_most_matching_braces(translated, original)
    translated = normalize_reference_command_arguments(translated)
    return translated

def normalize_command_argument_punctuation(match: re.Match) -> str:
    command = match.group(1)
    argument = match.group(2).replace("：", ":").replace("，", ",")
    return f"\\{command}" + "{" + argument + "}"

def join_most_matching_braces(translated: str, original: str) -> str:
    trans_pos = 0
    orig_pos = 0

    def find_next(source: str, chars: set[str], start: int) -> tuple[int | None, str | None]:
        pos = start
        while pos < len(source):
            if source[pos] in chars:
                return pos, source[pos]
            pos += 1
        return None, None

    while True:
        next_orig, char = find_next(original, {"{", "}"}, orig_pos)
        if next_orig is None or char is None:
            break
        next_trans, _ = find_next(translated, {char}, trans_pos)
        if next_trans is None:
            break
        orig_pos = next_orig + 1
        trans_pos = next_trans + 1
    return translated[:trans_pos] + original[orig_pos:]

def brace_balance(text: str) -> int:
    balance = 0
    i = 0
    while i < len(text):
        if text[i] == "\\":
            i += 2
            continue
        if text[i] == "{":
            balance += 1
        elif text[i] == "}":
            balance -= 1
        i += 1
    return balance

def pdf_is_readable(pdf: Path) -> bool:
    if not pdf.is_file() or not shutil.which("pdfinfo"):
        return pdf.is_file()
    proc = subprocess.run(["pdfinfo", str(pdf)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return proc.returncode == 0 and "Pages:" in proc.stdout

def compiler_for(tex_path: Path) -> str:
    content = tex_path.read_text(encoding="utf-8", errors="ignore")[:10000]
    needs_unicode = any(token in content for token in ["ctex", "xeCJK", "fontspec", "xetex", "unicode-math", "中文"])
    if needs_unicode and shutil.which("lualatex"):
        return "lualatex"
    if needs_unicode and shutil.which("xelatex"):
        return "xelatex"
    if shutil.which("pdflatex"):
        return "pdflatex"
    if shutil.which("xelatex"):
        return "xelatex"
    if shutil.which("lualatex"):
        return "lualatex"
    die("no supported LaTeX compiler was found on PATH")

def run(cmd: list[str], cwd: Path, timeout: int = 120) -> bool:
    print("+ " + " ".join(cmd))
    try:
        proc = subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        print("command timed out", file=sys.stderr)
        return False
    if proc.returncode != 0:
        print(proc.stdout[-4000:], file=sys.stderr)
        return False
    return True

def compile_attempt(compiler: str, work: Path, main: str, timeout: int) -> tuple[bool, bool]:
    pdf = work / f"{main}.pdf"
    if pdf.exists():
        try:
            pdf.unlink()
        except PermissionError:
            print(f"warning: could not remove locked PDF before rebuild: {pdf}", file=sys.stderr)
    ok = run([compiler, "-interaction=batchmode", "-file-line-error", f"{main}.tex"], work, timeout)
    aux = work / f"{main}.aux"
    if aux.exists() and shutil.which("bibtex"):
        aux_text = aux.read_text(encoding="utf-8", errors="ignore")
        if r"\bibdata" in aux_text:
            bib_matches = re.findall(r"\\bibdata\{([^}]*)\}", aux_text)
            bib_names: list[str] = []
            for match in bib_matches:
                bib_names.extend(part.strip() for part in match.split(",") if part.strip())
            bib_files = [work / f"{name}.bib" for name in bib_names]
            if any(path.exists() for path in bib_files):
                run(["bibtex", main], work, timeout)
            elif (work / f"{main}.bbl").exists():
                print(f"warning: no .bib file found for {main}; reusing existing {main}.bbl", file=sys.stderr)
    ok = run([compiler, "-interaction=batchmode", "-file-line-error", f"{main}.tex"], work, timeout) and ok
    ok = run([compiler, "-interaction=batchmode", "-file-line-error", f"{main}.tex"], work, timeout) and ok
    return pdf_is_readable(pdf), ok

def collect_critical_latex_issues(log_path: Path) -> list[str]:
    if not log_path.is_file():
        return []
    patterns = [
        r"^!",
        r"Fatal",
        r"Emergency",
        r"Undefined control sequence",
        r"LaTeX Error",
        r"Missing \$ inserted",
        r"Runaway argument",
        r"File ended while scanning",
    ]
    combined = re.compile("|".join(patterns), re.M)
    issues = []
    for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if combined.search(line):
            issues.append(line.strip())
    return issues
