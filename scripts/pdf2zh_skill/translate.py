from __future__ import annotations

from .common import *
from .latex_ops import fix_translation, mask_latex_blocks_for_translation, unmask_latex_blocks

TRANSLATION_API_KEY_ENV = "PDF2ZH_TRANSLATION_API_KEY"
TRANSLATION_BASE_URL_ENV = "PDF2ZH_TRANSLATION_BASE_URL"
TRANSLATION_MODEL_ENV = "PDF2ZH_TRANSLATION_MODEL"


def resolve_translation_settings(
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
) -> tuple[str, str, str]:
    api_key = api_key or os.environ.get(TRANSLATION_API_KEY_ENV)
    base_url = base_url or os.environ.get(TRANSLATION_BASE_URL_ENV)
    model = model or os.environ.get(TRANSLATION_MODEL_ENV)
    missing = []
    if not api_key:
        missing.append(TRANSLATION_API_KEY_ENV)
    if not base_url:
        missing.append(TRANSLATION_BASE_URL_ENV)
    if not model:
        missing.append(TRANSLATION_MODEL_ENV)
    if missing:
        die(
            "translation API is not configured; missing "
            + ", ".join(missing)
            + ". Put them in .env or pass --api-key/--base-url/--model."
        )
    return api_key, base_url, model


def masked_plain_text_for_terms(text: str) -> str:
    masked, _ = mask_latex_blocks_for_translation(text)
    masked = re.sub(r"__LATEX_BLOCK_\d+__", " ", masked)
    masked = masked.replace("\\", " ")
    return compact_whitespace(masked)

def english_tokens(text: str) -> list[str]:
    return re.findall(r"[A-Za-z][A-Za-z0-9-]*", text)

def looks_generic_phrase(phrase: str) -> bool:
    return phrase in GENERIC_TERM_BLACKLIST

def candidate_phrase_valid(words: list[str]) -> bool:
    if not words:
        return False
    lowered = [word.lower() for word in words]
    if lowered[0] in EN_STOPWORDS or lowered[-1] in EN_STOPWORDS:
        return False
    if all(word in EN_STOPWORDS for word in lowered):
        return False
    if sum(len(word) >= 4 for word in lowered) == 0:
        return False
    phrase = " ".join(lowered)
    if len(phrase) < 6 or len(phrase) > 48:
        return False
    if looks_generic_phrase(phrase):
        return False
    return True

def pattern_for_source_term(source: str) -> re.Pattern[str]:
    escaped = re.escape(source.strip())
    escaped = escaped.replace(r"\ ", r"\s+")
    return re.compile(rf"(?<![A-Za-z0-9]){escaped}(?![A-Za-z0-9])", re.I)

def context_snippets_for_term(source: str, texts: list[str], max_samples: int = 2) -> list[str]:
    pattern = pattern_for_source_term(source)
    snippets: list[str] = []
    for text in texts:
        for match in pattern.finditer(text):
            start = max(0, match.start() - 70)
            end = min(len(text), match.end() + 70)
            snippet = compact_whitespace(text[start:end])
            if snippet and snippet not in snippets:
                snippets.append(snippet)
            if len(snippets) >= max_samples:
                return snippets
    return snippets

def collect_glossary_candidates(segments: list[dict], max_candidates: int = 80) -> list[dict]:
    acronym_counts: Counter[str] = Counter()
    phrase_counts: Counter[str] = Counter()
    plain_texts: list[str] = []

    for segment in segments:
        plain = masked_plain_text_for_terms(segment["text"])
        plain_texts.append(plain)

        for acronym in re.findall(r"\b[A-Z][A-Z0-9-]{1,14}\b", plain):
            if acronym.lower() not in EN_STOPWORDS and len(acronym) >= 2:
                acronym_counts[acronym] += 1

        words = english_tokens(plain)
        lowered_words = [word.lower() for word in words]
        for ngram_size in range(2, 5):
            for index in range(0, len(lowered_words) - ngram_size + 1):
                window = lowered_words[index : index + ngram_size]
                if not candidate_phrase_valid(window):
                    continue
                phrase_counts[" ".join(window)] += 1

    candidates: list[dict] = []
    for source, count in acronym_counts.items():
        if count < 2:
            continue
        candidates.append(
            {
                "source": source,
                "count": count,
                "kind": "abbreviation",
                "contexts": context_snippets_for_term(source, plain_texts),
            }
        )

    for source, count in phrase_counts.items():
        if count < 2:
            continue
        candidates.append(
            {
                "source": source,
                "count": count,
                "kind": "term",
                "contexts": context_snippets_for_term(source, plain_texts),
            }
        )

    def score(item: dict) -> tuple[int, int, int, str]:
        kind_bonus = 3 if item["kind"] == "abbreviation" else 1
        token_count = len(item["source"].split())
        return (item["count"] * kind_bonus, item["count"], token_count, item["source"])

    candidates.sort(key=score, reverse=True)
    trimmed = candidates[:max_candidates]
    log(f"Glossary: extracted {len(trimmed)} candidate terms from {len(segments)} segments")
    return trimmed

def call_chat_text(
    *,
    api_key: str,
    base_url: str,
    model: str,
    messages: list[dict[str, str]],
    timeout: int,
    max_retries: int,
    temperature: float = 0.1,
) -> str:
    import requests

    body = {
        "model": model,
        "messages": messages,
        "thinking": {"type": "disabled"},
        "temperature": temperature,
        "stream": False,
    }
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
    url = base_url.rstrip("/") + "/chat/completions"
    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            response = requests.post(url, headers=headers, json=body, timeout=timeout)
            if response.status_code in {429, 500, 502, 503, 504} and attempt < max_retries:
                last_error = f"HTTP {response.status_code}: {response.text[:500]}"
                time.sleep(min(30, 2 * attempt))
                continue
            response.raise_for_status()
            payload = response.json()
            return (payload["choices"][0]["message"].get("content") or "").strip()
        except Exception as exc:
            last_error = repr(exc)
            if attempt < max_retries:
                time.sleep(min(30, 2 * attempt))
                continue
    die(f"translation API request failed after {max_retries} attempts: {last_error}")

def call_chat_json(
    *,
    api_key: str,
    base_url: str,
    model: str,
    messages: list[dict[str, str]],
    timeout: int,
    max_retries: int,
) -> dict | list:
    last_error = None
    for attempt in range(1, max_retries + 1):
        content = call_chat_text(
            api_key=api_key,
            base_url=base_url,
            model=model,
            messages=messages,
            timeout=timeout,
            max_retries=1,
            temperature=0.0,
        )
        try:
            payload = json.loads(strip_code_fence(content))
            if isinstance(payload, (dict, list)):
                return payload
            last_error = f"unexpected JSON root type: {type(payload)!r}"
        except Exception as exc:
            last_error = repr(exc)
        if attempt < max_retries:
            time.sleep(min(10, attempt * 2))
    die(f"translation API JSON response invalid after {max_retries} attempts: {last_error}")

def normalize_glossary_terms(payload: dict | list, max_terms: int) -> list[dict]:
    rows = payload.get("terms", []) if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        return []
    terms: list[dict] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        source = compact_whitespace(str(row.get("source", "")))
        translation = compact_whitespace(str(row.get("translation", "")))
        if not source or not translation:
            continue
        key = source.lower()
        if key in seen:
            continue
        seen.add(key)
        aliases = []
        raw_aliases = row.get("aliases") or []
        if isinstance(raw_aliases, list):
            aliases = [compact_whitespace(str(alias)) for alias in raw_aliases if compact_whitespace(str(alias))]
        terms.append(
            {
                "source": source,
                "translation": translation,
                "type": compact_whitespace(str(row.get("type", "term"))) or "term",
                "aliases": aliases[:6],
                "note": compact_whitespace(str(row.get("note", ""))),
            }
        )
        if len(terms) >= max_terms:
            break
    return terms

def format_glossary_for_prompt(terms: list[dict], max_terms: int = 40) -> str:
    if not terms:
        return ""
    lines = ["Paper-level glossary. Use these Chinese translations consistently across the whole article:"]
    for term in terms[:max_terms]:
        alias_text = f" | aliases: {', '.join(term['aliases'][:3])}" if term.get("aliases") else ""
        note_text = f" | note: {term['note']}" if term.get("note") else ""
        lines.append(f"- {term['source']} -> {term['translation']}{alias_text}{note_text}")
    return "\n".join(lines)

def load_glossary_terms(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    return normalize_glossary_terms(payload, max_terms=200)

def glossary_terms_for_segment(text: str, terms: list[dict]) -> list[dict]:
    matched: list[dict] = []
    seen: set[str] = set()
    for term in terms:
        variants = [term["source"], *(term.get("aliases") or [])]
        for variant in variants:
            if not variant:
                continue
            if pattern_for_source_term(variant).search(text):
                key = term["source"].lower()
                if key not in seen:
                    matched.append(term)
                    seen.add(key)
                break
    return matched

def missing_preferred_terms(translated: str, matched_terms: list[dict]) -> list[dict]:
    missing = []
    for term in matched_terms:
        preferred = term["translation"]
        if preferred and preferred not in translated:
            missing.append(term)
    return missing

def call_translation_api(
    text: str,
    *,
    api_key: str,
    base_url: str,
    model: str,
    requirement: str,
    glossary_text: str,
    timeout: int,
    max_retries: int,
) -> str:
    masked_text, protected = mask_latex_blocks_for_translation(text)
    style_rule = (
        "\nAdditional user glossary or style rule:\n"
        f"{requirement.strip()}\n"
        if requirement.strip()
        else ""
    )
    paper_glossary = (
        "\nPaper-level terminology constraints:\n"
        f"{glossary_text.strip()}\n"
        if glossary_text.strip()
        else ""
    )
    messages = [
        {
            "role": "system",
            "content": "You are a professional academic LaTeX translator. Return valid LaTeX text, not Markdown.",
        },
        {
            "role": "user",
            "content": (
                "Below is a section from an English academic paper, translate it into Chinese. "
                f"{style_rule}"
                f"{paper_glossary}"
                "Do not modify any latex command such as \\section, \\cite, \\begin, \\item and equations. "
                "Keep reference and citation commands byte-for-byte unchanged, including \\Cref{...}, \\cref{...}, \\ref{...}, \\eqref{...}, \\pageref{...}, \\nameref{...}, \\cite{...}, \\citep{...}, \\citet{...}; never translate keys and never escape underscores inside their braces. "
                "Do not modify placeholders like __LATEX_BLOCK_0000__; keep them byte-for-byte unchanged. "
                "If a paper-level glossary specifies a preferred translation for a term, use that translation consistently. "
                "Do not use Markdown syntax such as **bold**, __bold__, `code`, headings, or bullet lists. "
                "If emphasis is already present in LaTeX, preserve the original LaTeX command instead of creating Markdown. "
                "Answer me only with the translated text:"
                f"\n\n{masked_text}"
            ),
        },
    ]
    content = call_chat_text(
        api_key=api_key,
        base_url=base_url,
        model=model,
        messages=messages,
        timeout=timeout,
        max_retries=max_retries,
        temperature=0.1,
    )
    translated = unmask_latex_blocks(strip_code_fence(content), protected)
    return strip_leading_source_echo(text, translated)

def translate_with_retries(
    text: str,
    *,
    api_key: str,
    base_url: str,
    model: str,
    requirement: str,
    glossary_text: str,
    timeout: int,
    max_retries: int,
    retry_untranslated: int,
) -> tuple[str, int, bool]:
    translated = call_translation_api(
        text,
        api_key=api_key,
        base_url=base_url,
        model=model,
        requirement=requirement,
        glossary_text=glossary_text,
        timeout=timeout,
        max_retries=max_retries,
    )
    attempts = 1
    looks_untranslated = is_probably_untranslated(text, translated)
    while looks_untranslated and attempts <= retry_untranslated:
        translated = call_translation_api(
            text,
            api_key=api_key,
            base_url=base_url,
            model=model,
            requirement=(
                requirement.strip()
                + "\nThe previous attempt left too much English. Translate the prose into idiomatic Chinese while preserving LaTeX exactly, especially reference and citation command keys."
            ).strip(),
            glossary_text=glossary_text,
            timeout=timeout,
            max_retries=max_retries,
        )
        attempts += 1
        looks_untranslated = is_probably_untranslated(text, translated)
    return translated, attempts, looks_untranslated

def revise_translation_for_consistency(
    *,
    original: str,
    current_translation: str,
    matched_terms: list[dict],
    api_key: str,
    base_url: str,
    model: str,
    requirement: str,
    timeout: int,
    max_retries: int,
) -> str:
    glossary_block = format_glossary_for_prompt(matched_terms, max_terms=len(matched_terms))
    masked_text, protected = mask_latex_blocks_for_translation(original)
    masked_current = current_translation
    for token, original_block in protected.items():
        masked_current = masked_current.replace(original_block, token)
    requirement_block = (
        "\nAdditional user style rule:\n"
        f"{requirement.strip()}\n"
        if requirement.strip()
        else ""
    )
    messages = [
        {
            "role": "system",
            "content": "You are revising a Chinese academic LaTeX translation for terminology consistency. Return valid LaTeX text, not Markdown.",
        },
        {
            "role": "user",
            "content": (
                "Revise the current Chinese translation of one LaTeX segment so it uses the preferred paper-level terminology consistently. "
                "Keep all LaTeX commands, environments, labels, equations, and placeholders unchanged. "
                "Keep reference and citation commands byte-for-byte unchanged, including \\Cref{...}, \\cref{...}, \\ref{...}, \\eqref{...}, \\pageref{...}, \\nameref{...}, \\cite{...}, \\citep{...}, \\citet{...}; never translate keys and never escape underscores inside their braces. "
                "Do not use Markdown syntax such as **bold**, __bold__, `code`, headings, or bullet lists. "
                "Do not add explanations. Return only the revised translated text.\n"
                f"{requirement_block}"
                f"\nRequired terminology for this segment:\n{glossary_block}\n"
                "Original English segment:\n"
                f"{masked_text}\n\n"
                "Current Chinese translation:\n"
                f"{masked_current}"
            ),
        },
    ]
    revised = call_chat_text(
        api_key=api_key,
        base_url=base_url,
        model=model,
        messages=messages,
        timeout=timeout,
        max_retries=max_retries,
        temperature=0.0,
    )
    revised_text = unmask_latex_blocks(strip_code_fence(revised), protected)
    return strip_leading_source_echo(original, revised_text)
