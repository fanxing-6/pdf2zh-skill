from __future__ import annotations

from .common import *

def prepare_vision_review_pack(
    *,
    source_pdf: Path,
    translated_pdf: Path,
    out_dir: Path,
    pages_spec: str,
    tex_path: Path | None = None,
) -> Path:
    source_total = pdf_page_count(source_pdf)
    translated_total = pdf_page_count(translated_pdf)
    total_pages = None
    if source_total is not None and translated_total is not None:
        total_pages = min(source_total, translated_total)
    elif source_total is not None:
        total_pages = source_total
    elif translated_total is not None:
        total_pages = translated_total

    pages = parse_page_spec(pages_spec, total_pages=total_pages)
    pack_dir = out_dir.resolve()
    if pack_dir.exists():
        shutil.rmtree(pack_dir)
    pack_dir.mkdir(parents=True, exist_ok=True)

    source_dir = pack_dir / "source_pages"
    translated_dir = pack_dir / "translated_pages"
    source_images = render_pdf_pages(source_pdf, source_dir, pages, "source")
    translated_images = render_pdf_pages(translated_pdf, translated_dir, pages, "translated")

    manifest = {
        "source_pdf": str(source_pdf),
        "translated_pdf": str(translated_pdf),
        "pages": pages,
        "source_images": [str(path) for path in source_images],
        "translated_images": [str(path) for path in translated_images],
        "tex": str(tex_path) if tex_path else None,
    }
    if is_wsl():
        manifest.update(
            {
                "source_pdf_windows": windows_visible_path(source_pdf),
                "translated_pdf_windows": windows_visible_path(translated_pdf),
                "tex_windows": windows_visible_path(tex_path) if tex_path else None,
                "source_images_windows": [windows_visible_path(path) for path in source_images],
                "translated_images_windows": [windows_visible_path(path) for path in translated_images],
            }
        )

    (pack_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return pack_dir
