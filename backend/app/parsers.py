from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pypdf import PdfReader


SUPPORTED_EXTENSIONS = {".txt", ".md", ".csv", ".json", ".pdf"}
SUPPORTED_CONTENT_TYPES = {
    "text/plain",
    "text/markdown",
    "text/csv",
    "application/csv",
    "application/json",
    "application/pdf",
}


@dataclass(frozen=True)
class ParsedDocument:
    raw_text: str
    parser_type: str
    normalized_preview: str


class UnsupportedDocumentType(ValueError):
    pass


def parse_upload(
    filename: str | None, content_type: str | None, content: bytes
) -> ParsedDocument:
    """Normalize the one-week MVP file types into text stored in PostgreSQL.

    Supported: txt, md, csv, json, and text-based PDFs. Scanned PDFs/images are
    intentionally out of scope for this MVP because they require OCR.
    """
    suffix = Path(filename or "").suffix.lower()
    ctype = (content_type or "").split(";")[0].lower()

    if suffix in {".txt", ".md"} or ctype in {"text/plain", "text/markdown"}:
        text = content.decode("utf-8", errors="replace")
        return ParsedDocument(
            raw_text=text, parser_type="plain_text", normalized_preview=text[:500]
        )

    if suffix == ".csv" or ctype in {"text/csv", "application/csv"}:
        return _parse_csv(content)

    if suffix == ".json" or ctype == "application/json":
        return _parse_json(content)

    if suffix == ".pdf" or ctype == "application/pdf":
        return _parse_pdf(content)

    supported = ", ".join(sorted(SUPPORTED_EXTENSIONS))
    raise UnsupportedDocumentType(f"Unsupported file type. MVP supports: {supported}.")


def parse_raw_text(raw_text: str) -> ParsedDocument:
    return ParsedDocument(
        raw_text=raw_text, parser_type="raw_text", normalized_preview=raw_text[:500]
    )


def _parse_csv(content: bytes) -> ParsedDocument:
    text = content.decode("utf-8-sig", errors="replace")
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample)
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    rows = list(reader)
    headers = reader.fieldnames or []

    lines = [f"CSV document with {len(rows)} rows and {len(headers)} columns."]
    if headers:
        lines.append("Columns: " + ", ".join(headers))
    for idx, row in enumerate(rows[:10], start=1):
        pairs = [f"{key}: {value}" for key, value in row.items()]
        lines.append(f"Preview row {idx}: " + "; ".join(pairs))
    if len(rows) > 10:
        lines.append(f"... {len(rows) - 10} additional rows omitted from preview.")

    # Store the full parsed CSV payload in PostgreSQL as JSON so the worker can
    # create one extraction row per CSV record field. This avoids making the UI
    # depend on a truncated preview and keeps structured formats deterministic.
    lines.append("CSV_JSON_RECORDS:")
    lines.append(json.dumps(rows, indent=2, ensure_ascii=False))

    normalized = "\n".join(lines)
    return ParsedDocument(
        raw_text=normalized, parser_type="csv", normalized_preview=normalized[:500]
    )


def _parse_json(content: bytes) -> ParsedDocument:
    text = content.decode("utf-8-sig", errors="replace")
    try:
        parsed: Any = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON: {exc.msg}") from exc
    pretty = json.dumps(parsed, indent=2, ensure_ascii=False)
    if isinstance(parsed, list):
        prefix = f"JSON document containing a list with {len(parsed)} items.\n"
    elif isinstance(parsed, dict):
        prefix = (
            "JSON document containing an object with keys: "
            + ", ".join(map(str, parsed.keys()))
            + ".\n"
        )
    else:
        prefix = f"JSON document containing {type(parsed).__name__}.\n"
    raw_text = prefix + pretty
    return ParsedDocument(
        raw_text=raw_text, parser_type="json", normalized_preview=raw_text[:500]
    )


def _parse_pdf(content: bytes) -> ParsedDocument:
    reader = PdfReader(io.BytesIO(content))
    pages: list[str] = []
    for page_number, page in enumerate(reader.pages, start=1):
        page_text = page.extract_text() or ""
        if page_text.strip():
            pages.append(f"--- Page {page_number} ---\n{page_text.strip()}")
    raw_text = "\n\n".join(pages).strip()
    if not raw_text:
        raise ValueError(
            "No selectable text found in PDF. Scanned PDFs/images need OCR and are outside the one-week MVP scope."
        )
    return ParsedDocument(
        raw_text=raw_text, parser_type="pdf_text", normalized_preview=raw_text[:500]
    )
