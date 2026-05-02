from __future__ import annotations

from .common import *

def arxiv_id_from_url(url: str) -> str | None:
    parsed = urlparse(url)
    if parsed.netloc not in {"arxiv.org", "www.arxiv.org"}:
        return None
    path = parsed.path.strip("/")
    prefixes = ("abs/", "pdf/", "src/", "e-print/")
    identifier = None
    for prefix in prefixes:
        if path.startswith(prefix):
            identifier = path[len(prefix) :]
            break
    if not identifier:
        return None
    if identifier.endswith(".pdf"):
        identifier = identifier[:-4]
    identifier = identifier.strip("/")
    patterns = [
        r"\d{4}\.\d{4,5}(?:v\d+)?",
        r"[a-z\-]+(?:\.[A-Z]{2})?/\d{7}(?:v\d+)?",
    ]
    if any(re.fullmatch(pattern, identifier) for pattern in patterns):
        return identifier
    return None


def arxiv_pdf_url(arxiv_id: str) -> str:
    return f"https://arxiv.org/pdf/{arxiv_id}.pdf"


def arxiv_source_urls(arxiv_id: str) -> list[str]:
    return [
        f"https://arxiv.org/src/{arxiv_id}",
        f"https://arxiv.org/e-print/{arxiv_id}",
    ]


def extract_arxiv_source_archive(archive_path: Path, project: Path) -> None:
    import gzip
    import tarfile

    def write_main_tex(data: bytes) -> None:
        project.mkdir(parents=True, exist_ok=True)
        (project / "main.tex").write_bytes(data)

    project.mkdir(parents=True, exist_ok=True)
    try:
        with tarfile.open(archive_path, "r:*") as tf:
            tf.extractall(project)
        return
    except tarfile.ReadError:
        pass

    try:
        with gzip.open(archive_path, "rb") as fh:
            inflated = fh.read()
    except OSError:
        inflated = b""

    if inflated:
        temp_inflated = archive_path.with_suffix(".inflated")
        temp_inflated.write_bytes(inflated)
        try:
            with tarfile.open(temp_inflated, "r:*") as tf:
                tf.extractall(project)
            return
        except tarfile.ReadError:
            pass
        finally:
            temp_inflated.unlink(missing_ok=True)
        if b"\\documentclass" in inflated or b"\\begin{document}" in inflated:
            write_main_tex(inflated)
            return

    raw = archive_path.read_bytes()
    if b"\\documentclass" in raw or b"\\begin{document}" in raw:
        write_main_tex(raw)
        return

    die(f"arXiv source archive could not be extracted: {archive_path}")


def download_arxiv_source_project(url: str, out: Path) -> tuple[Path, Path] | None:
    import requests

    arxiv_id = arxiv_id_from_url(url)
    if not arxiv_id:
        return None

    out.mkdir(parents=True, exist_ok=True)
    archive = out / f"{slugify(arxiv_id)}_source"
    project = out / "project"
    if project.exists():
        shutil.rmtree(project)

    source_downloaded = False
    last_error = None
    for source_url in arxiv_source_urls(arxiv_id):
        log(f"arXiv: probing source package {safe_url_label(source_url)}")
        try:
            response = requests.get(
                source_url,
                headers={"User-Agent": "pdf2zh-skill"},
                timeout=(15, 180),
                stream=True,
                allow_redirects=True,
            )
            if response.status_code == 404:
                last_error = "404 not found"
                continue
            response.raise_for_status()
            with archive.open("wb") as fh:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        fh.write(chunk)
            source_downloaded = True
            break
        except Exception as exc:
            last_error = repr(exc)
            log(f"arXiv: source download failed for {safe_url_label(source_url)}: {last_error}")
            continue

    if not source_downloaded:
        log(f"arXiv: no usable source package found for {arxiv_id}: {last_error}")
        return None

    extract_arxiv_source_archive(archive, project)
    if not any(project.rglob("*.tex")):
        die(f"arXiv source package for {arxiv_id} does not contain any .tex files")

    pdf_path = out / f"{slugify(arxiv_id)}.pdf"
    download_url(arxiv_pdf_url(arxiv_id), pdf_path)
    log(f"arXiv: using source package for {arxiv_id}")
    return project, pdf_path


def convert_doc2x(pdf: Path, out: Path, api_key: str | None, model: str) -> Path:
    api_key = api_key or os.environ.get("DOC2X_API_KEY")
    if not api_key:
        die("DOC2X_API_KEY is required for --method doc2x")
    headers = {"Authorization": f"Bearer {api_key}"}
    staged_pdf, temp_dir = stage_upload_source(pdf)

    try:
        log(f"DOC2X: requesting upload URL with model={model}")
        pre = http_request(
            "POST",
            "https://v2.doc2x.noedgeai.com/api/v2/parse/preupload",
            headers=headers,
            json_body={"model": model},
            timeout=30,
        )
        pre_json = pre.json()
        if not doc2x_code_ok(pre_json):
            die(f"DOC2X preupload failed: {pre_json}")
        uid = pre_json["data"]["uid"]
        upload_url = pre_json["data"]["url"]
        log(f"DOC2X: uid={uid}, upload_target={safe_url_label(upload_url)}")

        size_mb = staged_pdf.stat().st_size / (1024 * 1024)
        upload_timeout = 120
        log(f"DOC2X: uploading PDF ({size_mb:.1f} MiB) using official requests.put(data=file) style")
        upload_ok, upload_error = put_file_with_retries(
            upload_url,
            staged_pdf,
            timeout_seconds=upload_timeout,
            max_retries=1,
            label="DOC2X upload",
        )
        if not upload_ok:
            task_seen, status_note = wait_doc2x_upload_seen(uid, headers, wait_seconds=35)
            if task_seen:
                log(f"DOC2X: upload response failed, but server status is {status_note}; continuing")
            else:
                die(f"DOC2X upload failed: {upload_error}; status probe={status_note}")

        log("DOC2X: waiting for parse")
        last_status_note = None
        for poll_index in range(1, 81):
            status_json = get_doc2x_status(uid, headers)
            data = status_json.get("data", {})
            status_note = f"status={data.get('status')}, progress={data.get('progress')}"
            if status_note != last_status_note or poll_index == 1:
                log(f"DOC2X: parse poll {poll_index}/80 {status_note}")
                last_status_note = status_note
            if data.get("status") == "success":
                break
            if data.get("status") != "processing":
                die(f"DOC2X parse failed for uid {uid}: {status_json}")
            time.sleep(3)
        else:
            die(f"DOC2X parse timed out for uid {uid}")

        log("DOC2X: requesting TeX conversion")
        convert = http_request(
            "POST",
            "https://v2.doc2x.noedgeai.com/api/v2/convert/parse",
            headers=headers,
            json_body={
                "uid": uid,
                "to": "tex",
                "formula_mode": "dollar",
                "filename": "output",
                "merge_cross_page_forms": True,
                "formula_level": 0,
            },
            timeout=30,
        )
        if not doc2x_code_ok(convert.json()):
            die(f"DOC2X convert request failed: {convert.json()}")

        log("DOC2X: waiting for TeX archive")
        result_url = None
        last_convert_note = None
        for poll_index in range(1, 49):
            result = http_request(
                "GET",
                f"https://v2.doc2x.noedgeai.com/api/v2/convert/parse/result?uid={uid}",
                headers=headers,
                timeout=30,
            )
            data = result.json().get("data", {})
            if not doc2x_code_ok(result.json()):
                die(f"DOC2X convert status failed for uid {uid}: {result.json()}")
            convert_note = f"status={data.get('status')}, url_ready={bool(data.get('url'))}"
            if convert_note != last_convert_note or poll_index == 1:
                log(f"DOC2X: convert poll {poll_index}/48 {convert_note}")
                last_convert_note = convert_note
            if data.get("status") == "success":
                result_url = data.get("url")
                break
            if data.get("status") != "processing":
                die(f"DOC2X TeX conversion failed for uid {uid}: {result.json()}")
            time.sleep(3)
        if not result_url:
            die(f"DOC2X TeX conversion timed out for uid {uid}")

        out.mkdir(parents=True, exist_ok=True)
        archive = out / "doc2x_tex.zip"
        log(f"DOC2X: downloading TeX archive from {safe_url_label(result_url)}")
        started = time.monotonic()
        with urlopen(Request(result_url, headers={"User-Agent": "pdf2zh-skill"}), timeout=120) as response:
            archive.write_bytes(response.read())
        log(f"DOC2X: archive saved to {archive} ({archive.stat().st_size} bytes) in {time.monotonic() - started:.1f}s")

        project = out / "project"
        if project.exists():
            shutil.rmtree(project)
        project.mkdir(parents=True)
        with zipfile.ZipFile(archive, "r") as zf:
            zf.extractall(project)
        log(str(project))
        return project
    finally:
        if temp_dir is not None:
            shutil.rmtree(temp_dir, ignore_errors=True)

def convert_mathpix(pdf: Path, out: Path, app_id: str | None, app_key: str | None) -> Path:
    import requests

    app_id = app_id or os.environ.get("MATHPIX_APPID")
    app_key = app_key or os.environ.get("MATHPIX_APPKEY")
    if not app_id or not app_key:
        die("MATHPIX_APPID and MATHPIX_APPKEY are required for --method mathpix")
    headers = {"app_id": app_id, "app_key": app_key}
    options = {"conversion_formats": {"tex.zip": True}, "math_inline_delimiters": ["$", "$"], "rm_spaces": True}

    print("Mathpix: uploading PDF")
    with pdf.open("rb") as fh:
        response = requests.post(
            "https://api.mathpix.com/v3/pdf",
            headers=headers,
            data={"options_json": json.dumps(options)},
            files={"file": fh},
            timeout=120,
        )
    response.raise_for_status()
    pdf_id = response.json()["pdf_id"]

    print("Mathpix: waiting for conversion")
    for _ in range(180):
        status = requests.get(f"https://api.mathpix.com/v3/pdf/{pdf_id}", headers=headers, timeout=30)
        status.raise_for_status()
        payload = status.json()
        if payload.get("status") == "completed":
            break
        if payload.get("status") == "error":
            die(f"Mathpix conversion failed: {payload}")
        time.sleep(5)
    else:
        die(f"Mathpix conversion timed out for pdf_id {pdf_id}")

    out.mkdir(parents=True, exist_ok=True)
    archive = out / "mathpix_tex.zip"
    tex_zip = requests.get(f"https://api.mathpix.com/v3/pdf/{pdf_id}.tex", headers=headers, timeout=120)
    tex_zip.raise_for_status()
    archive.write_bytes(tex_zip.content)

    project = out / "project"
    if project.exists():
        shutil.rmtree(project)
    project.mkdir(parents=True)
    with zipfile.ZipFile(archive, "r") as zf:
        zf.extractall(project)
    print(project)
    return project

def download_url(url: str, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    import requests

    label = safe_url_label(url)
    log(f"Download: {label} -> {target}")
    for attempt in range(1, 4):
        try:
            started = time.monotonic()
            response = requests.get(
                url,
                headers={"User-Agent": "pdf2zh-skill"},
                timeout=(15, 180),
                stream=True,
                allow_redirects=True,
            )
            if response.status_code in {429, 500, 502, 503, 504} and attempt < 3:
                log(f"Download: attempt {attempt}/3 got HTTP {response.status_code}, retrying")
                time.sleep(min(10, attempt * 2))
                continue
            response.raise_for_status()
            with target.open("wb") as f:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        f.write(chunk)
            elapsed = time.monotonic() - started
            log(f"Download: wrote {target.stat().st_size} bytes in {elapsed:.1f}s")
            return
        except Exception as exc:
            log(f"Download: {label} attempt {attempt}/3 failed: {exc!r}")
            if attempt == 3:
                raise
            time.sleep(min(10, attempt * 2))

def put_file_with_retries(upload_url: str, pdf: Path, *, timeout_seconds: int, max_retries: int = 3, label: str = "upload") -> tuple[bool, str | None]:
    import requests
    from urllib.request import Request, urlopen

    last_error = None
    for attempt in range(1, max_retries + 1):
        started = time.monotonic()
        size = pdf.stat().st_size
        log(f"{label}: PUT {safe_url_label(upload_url)} attempt {attempt}/{max_retries}, {size} bytes")
        data = None
        with pdf.open("rb") as fh:
            data = fh.read()
        try:
            response = requests.put(upload_url, data=data, headers={"Content-Type": "application/pdf"}, timeout=(30, timeout_seconds))
            elapsed = time.monotonic() - started
            log(f"{label}: requests response HTTP {response.status_code} in {elapsed:.1f}s, {len(response.content)} bytes")
            if response.status_code == 200:
                return True, None
            last_error = f"requests HTTP {response.status_code}: {response.text[:300]}"
        except Exception as exc:
            elapsed = time.monotonic() - started
            log(f"{label}: requests failed in {elapsed:.1f}s: {exc!r}")
            last_error = repr(exc)

        try:
            started = time.monotonic()
            req = Request(upload_url, data=data, method="PUT")
            req.add_header("Content-Type", "application/pdf")
            req.add_header("Content-Length", str(size))
            with urlopen(req, timeout=timeout_seconds) as response:
                content = response.read()
            elapsed = time.monotonic() - started
            status = getattr(response, "status", 0)
            log(f"{label}: urllib response HTTP {status} in {elapsed:.1f}s, {len(content)} bytes")
            if status == 200:
                return True, None
            last_error = f"urllib HTTP {status}: {content[:300]!r}"
        except Exception as exc:
            elapsed = time.monotonic() - started
            log(f"{label}: urllib failed in {elapsed:.1f}s: {exc!r}")
            last_error = repr(exc)
        if attempt < max_retries:
            log(f"{label}: attempt {attempt} failed, retrying")
            time.sleep(5)
    return False, last_error

def latex_escape_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    return "".join(replacements.get(ch, ch) for ch in text)

def convert_text_fallback(pdf: Path, out: Path) -> Path:
    if not shutil.which("pdftotext"):
        die("pdftotext is required for --method text")
    out.mkdir(parents=True, exist_ok=True)
    project = out / "project"
    if project.exists():
        shutil.rmtree(project)
    project.mkdir(parents=True)
    text_path = out / "extracted.txt"
    proc = subprocess.run(["pdftotext", str(pdf), str(text_path)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if proc.returncode != 0:
        die(f"pdftotext failed: {proc.stdout}")
    raw = text_path.read_text(encoding="utf-8", errors="replace")
    raw = raw.replace("\f", "\n\n")
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", raw) if p.strip()]
    title = latex_escape_text(paragraphs[0]) if paragraphs else latex_escape_text(pdf.stem)
    body = "\n\n".join(latex_escape_text(p) + r"\par" for p in paragraphs[1:])
    tex = rf"""\documentclass{{article}}
\usepackage{{geometry}}
\geometry{{margin=1in}}
\title{{{title}}}
\author{{}}
\date{{}}
\begin{{document}}
\maketitle
\sloppy
{body}
\end{{document}}
"""
    (project / "main.tex").write_text(tex, encoding="utf-8")
    print(project)
    return project
