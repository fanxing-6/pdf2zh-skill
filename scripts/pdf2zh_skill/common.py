from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import html
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unicodedata
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable, Iterator
from urllib.parse import urlparse
from urllib.request import Request, urlopen

TRANSLATE = "translate"
PRESERVE = "preserve"

CJK_RADICAL_MAP = {
    "⻄": "西",
    "⻅": "见",
    "⻔": "门",
    "⻛": "风",
    "⻩": "黄",
}

EN_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "in",
    "into",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "their",
    "this",
    "to",
    "we",
    "with",
    "our",
    "via",
    "can",
    "using",
    "use",
    "used",
}

GENERIC_TERM_BLACKLIST = {
    "abstract unavailable",
    "related work",
    "introduction",
    "conclusion",
    "experimental results",
    "future work",
    "this paper",
    "our paper",
    "our method",
    "proposed method",
    "proposed framework",
    "state of the art",
}

@dataclass
class Node:
    kind: str
    text: str
    segment_id: str | None = None


def log(message: str) -> None:
    print(message, flush=True)

def die(message: str, code: int = 1) -> None:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(code)

def load_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open("r", encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                die(f"{path}:{line_no}: invalid JSONL: {exc}")
    return rows

def write_jsonl(path: Path, rows: Iterable[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

def safe_url_label(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"

def skill_root_dir() -> Path:
    return Path(__file__).resolve().parents[2]

def home_dir() -> Path:
    for key in ("HOME", "USERPROFILE"):
        value = os.environ.get(key)
        if value:
            return Path(value).expanduser()
    return Path.home()

def skill_home_dir() -> Path:
    override = os.environ.get("PDF2ZH_SKILL_HOME")
    if override:
        return Path(override).expanduser().resolve()
    return (home_dir() / "pdf2zh-skill").resolve()

def skill_tmp_dir() -> Path:
    override = os.environ.get("PDF2ZH_SKILL_TMPDIR")
    if override:
        path = Path(override).expanduser()
    else:
        base = (
            os.environ.get("TMPDIR")
            or os.environ.get("TEMP")
            or os.environ.get("TMP")
            or "/tmp"
        )
        path = Path(base).expanduser() / "pdf2zh-skill"
    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()

def slugify(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-._")
    return slug or "task"

def default_task_output_dir(source_hint: str) -> Path:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    name = slugify(Path(source_hint).stem or source_hint)
    return (skill_tmp_dir() / f"{stamp}-{name}").resolve()

def is_wsl() -> bool:
    if os.environ.get("WSL_DISTRO_NAME") or os.environ.get("WSL_INTEROP"):
        return True
    try:
        return "microsoft" in platform.release().lower()
    except Exception:
        return False

def windows_visible_path(path: Path) -> str | None:
    try:
        resolved = path.resolve()
    except Exception:
        resolved = path
    parts = resolved.parts
    if len(parts) >= 4 and parts[0] == "/" and parts[1] == "mnt" and len(parts[2]) == 1:
        drive = parts[2].upper() + ":"
        rest = "\\".join(parts[3:])
        return drive + ("\\" + rest if rest else "")
    return None

def log_path_hint(label: str, path: Path) -> None:
    log(f"{label}: {path}")
    if is_wsl():
        win_path = windows_visible_path(path)
        if win_path:
            log(f"{label} (Windows): {win_path}")

def parse_dotenv_lines(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        values[key] = value
    return values


def load_dotenv_file(path: Path, *, override: bool = False) -> bool:
    if not path.is_file():
        return False
    data = parse_dotenv_lines(path.read_text(encoding="utf-8"))
    for key, value in data.items():
        if override or key not in os.environ:
            os.environ[key] = value
    return True


def resolve_dotenv_candidates(explicit_env_file: str | None = None) -> list[Path]:
    candidates: list[Path] = []
    seen: set[Path] = set()

    def add(path: Path | None) -> None:
        if path is None:
            return
        resolved = path.expanduser().resolve()
        if resolved not in seen:
            seen.add(resolved)
            candidates.append(resolved)

    if explicit_env_file:
        add(Path(explicit_env_file))
    env_override = os.environ.get("PDF2ZH_SKILL_ENV_FILE")
    if env_override:
        add(Path(env_override))
    add(Path.cwd() / ".env")
    add(skill_root_dir() / ".env")
    try:
        add(skill_home_dir() / ".env")
    except Exception:
        pass
    return candidates


def load_dotenv_candidates(explicit_env_file: str | None = None) -> list[Path]:
    loaded: list[Path] = []
    for candidate in resolve_dotenv_candidates(explicit_env_file):
        if load_dotenv_file(candidate):
            loaded.append(candidate)
    return loaded

def pdf_page_count(pdf: Path) -> int | None:
    if not shutil.which("pdfinfo"):
        return None
    proc = subprocess.run(["pdfinfo", str(pdf)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        return None
    match = re.search(r"^Pages:\s+(\d+)\s*$", proc.stdout, re.M)
    return int(match.group(1)) if match else None

def parse_page_spec(spec: str, total_pages: int | None = None) -> list[int]:
    pages: set[int] = set()
    for raw_part in spec.split(","):
        part = raw_part.strip()
        if not part:
            continue
        if "-" in part:
            start_text, end_text = part.split("-", 1)
            start = int(start_text)
            end = int(end_text)
            if start > end:
                start, end = end, start
            for page in range(start, end + 1):
                pages.add(page)
        else:
            pages.add(int(part))
    ordered = sorted(page for page in pages if page >= 1)
    if total_pages is not None:
        ordered = [page for page in ordered if page <= total_pages]
    if not ordered:
        die(f"no valid pages resolved from page spec: {spec}")
    return ordered

def render_pdf_pages(pdf: Path, output_dir: Path, pages: list[int], prefix: str) -> list[Path]:
    if not shutil.which("pdftoppm"):
        die("pdftoppm is required for vision compare pack rendering")
    output_dir.mkdir(parents=True, exist_ok=True)
    rendered: list[Path] = []
    for page in pages:
        stem = output_dir / f"{prefix}_page_{page:03d}"
        cmd = [
            "pdftoppm",
            "-png",
            "-f",
            str(page),
            "-l",
            str(page),
            "-singlefile",
            str(pdf),
            str(stem),
        ]
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if proc.returncode != 0:
            die(f"pdftoppm failed for {pdf} page {page}: {proc.stderr or proc.stdout}")
        rendered_png = stem.with_suffix(".png")
        if not rendered_png.is_file():
            die(f"expected rendered page missing: {rendered_png}")
        rendered.append(rendered_png)
    return rendered

def http_request(method: str, url: str, *, headers=None, data=None, json_body=None, timeout=60, max_attempts=3):
    import requests

    label = f"{method.upper()} {safe_url_label(url)}"
    for attempt in range(1, max_attempts + 1):
        started = time.monotonic()
        log(f"HTTP: {label} attempt {attempt}/{max_attempts} timeout={timeout}s")
        try:
            response = requests.request(method, url, headers=headers, data=data, json=json_body, timeout=timeout)
            elapsed = time.monotonic() - started
            log(f"HTTP: {label} -> {response.status_code} in {elapsed:.1f}s, {len(response.content)} bytes")
            response.raise_for_status()
            return response
        except Exception as exc:
            elapsed = time.monotonic() - started
            log(f"HTTP: {label} failed in {elapsed:.1f}s: {exc!r}")
            if attempt == max_attempts:
                raise
            time.sleep(3)
    raise RuntimeError("unreachable")

def doc2x_code_ok(payload: dict) -> bool:
    return payload.get("code") in {"ok", "success"}

def get_doc2x_status(uid: str, headers: dict[str, str], *, die_on_business_error: bool = True) -> dict:
    response = http_request(
        "GET",
        f"https://v2.doc2x.noedgeai.com/api/v2/parse/status?uid={uid}",
        headers=headers,
        timeout=30,
    )
    payload = response.json()
    if not doc2x_code_ok(payload) and die_on_business_error:
        die(f"DOC2X parse status failed for uid {uid}: {payload}")
    return payload

def wait_doc2x_upload_seen(uid: str, headers: dict[str, str], wait_seconds: int) -> tuple[bool, str]:
    deadline = time.monotonic() + wait_seconds
    last_note = "not checked"
    while time.monotonic() < deadline:
        try:
            payload = get_doc2x_status(uid, headers, die_on_business_error=False)
            if doc2x_code_ok(payload):
                data = payload.get("data", {})
                status = data.get("status")
                progress = data.get("progress")
                last_note = f"status={status}, progress={progress}"
                if status in {"processing", "success", "failed"}:
                    return True, last_note
            else:
                last_note = f"business_error={payload}"
        except Exception as exc:
            last_note = repr(exc)
        time.sleep(3)
    return False, last_note

def stage_upload_source(pdf: Path) -> tuple[Path, Path | None]:
    raw = str(pdf)
    if not raw.startswith("/mnt/"):
        return pdf, None
    temp_dir = Path(tempfile.mkdtemp(prefix="pdf2zh-skill-upload-"))
    staged = temp_dir / pdf.name
    log(f"Upload: staging WSL-mounted PDF to {staged}")
    shutil.copy2(pdf, staged)
    return staged, temp_dir

def download_remote_pdf(url: str, out_dir: Path) -> Path:
    from .conversion import download_url

    out_dir.mkdir(parents=True, exist_ok=True)
    parsed = urlparse(url)
    base_name = Path(parsed.path).name or "remote.pdf"
    if not base_name.lower().endswith(".pdf"):
        base_name += ".pdf"
    target = out_dir / base_name
    download_url(url, target)
    return target

def strip_code_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text

def strip_leading_source_echo(original: str, translated: str) -> str:
    original = original.strip()
    translated = translated.strip()
    if not original or not translated:
        return translated
    position = translated.find(original)
    if position < 0 or position > 24:
        return translated
    candidate = translated[position + len(original) :].lstrip(" \n\r\t:：-")
    translated_cjk = sum("\u4e00" <= ch <= "\u9fff" for ch in candidate)
    return candidate if translated_cjk >= 8 else translated

def has_large_source_echo(original: str, translated: str) -> bool:
    original = compact_whitespace(original)
    translated = compact_whitespace(translated)
    if len(original) < 80 or len(translated) <= len(original) + 8:
        return False
    position = translated.find(original)
    return 0 <= position <= 24

def is_probably_untranslated(original: str, translated: str) -> bool:
    if has_large_source_echo(original, translated):
        return True
    original_letters = sum("A" <= ch <= "Z" or "a" <= ch <= "z" for ch in original)
    translated_cjk = sum("\u4e00" <= ch <= "\u9fff" for ch in translated)
    if original_letters < 80:
        return False
    return translated_cjk < max(8, original_letters // 80)

def compact_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()
