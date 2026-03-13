"""
PDF Service — Text and table extraction via pdfplumber.

Replaces the deprecated PyPDF2 with pdfplumber, which provides
accurate text extraction and proper table parsing (rows/columns).

Usage:
    from services.media.pdf_service import extract_pdf

    result = extract_pdf("/path/to/file.pdf")
    print(result["text"])        # Full text content
    print(result["num_pages"])   # Number of pages
    print(result["tables"])      # List of tables (list of rows)
    print(result["preview"])     # Short preview string
"""

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


def extract_pdf(path: str, max_pages: int = 50) -> Dict[str, Any]:
    """
    Extract text and tables from a PDF file.

    Args:
        path: Absolute path to the PDF file.
        max_pages: Maximum number of pages to process (default 50).

    Returns:
        Dict with keys:
            - text: Full extracted text (pages separated by headers)
            - tables: List of extracted tables (each table is a list of rows)
            - num_pages: Total number of pages in the PDF
            - preview: Short preview string for UI display
    """
    import pdfplumber

    text_parts: List[str] = []
    all_tables: List[List[List[str]]] = []

    try:
        with pdfplumber.open(path) as pdf:
            num_pages = len(pdf.pages)
            pages_to_process = min(num_pages, max_pages)

            for i in range(pages_to_process):
                page = pdf.pages[i]

                # Extract text
                page_text = page.extract_text() or ""
                if page_text.strip():
                    text_parts.append(f"[Page {i + 1}]\n{page_text.strip()}")

                # Extract tables
                tables = page.extract_tables()
                for table in tables:
                    if table:
                        cleaned = _clean_table(table)
                        if cleaned:
                            all_tables.append(cleaned)

            # Build full text
            full_text = "\n\n".join(text_parts)

            # Append tables as markdown if they exist
            if all_tables:
                table_text = _tables_to_markdown(all_tables)
                full_text += f"\n\n[Tables extracted]\n{table_text}"

            if not full_text.strip():
                full_text = "[PDF uploaded — no extractable text found]"

            # Preview
            preview_text = full_text[:150].replace("\n", " ")
            if num_pages > max_pages:
                preview = f"PDF ({num_pages} pages, first {max_pages} processed): {preview_text}..."
            else:
                preview = f"PDF ({num_pages} pages): {preview_text}..."

            logger.info(
                "PDF extracted: %d chars, %d pages, %d tables from %s",
                len(full_text), pages_to_process, len(all_tables), path,
            )

            return {
                "text": full_text,
                "tables": all_tables,
                "num_pages": num_pages,
                "preview": preview,
            }

    except Exception as e:
        logger.error("PDF extraction failed: %s", e)
        return {
            "text": f"[PDF uploaded — extraction failed: {e}]",
            "tables": [],
            "num_pages": 0,
            "preview": "PDF (extraction failed)",
        }


def _clean_table(table: List[List[str | None]]) -> List[List[str]]:
    """Remove None values and empty rows from a table."""
    cleaned = []
    for row in table:
        if row:
            cleaned_row = [(cell or "").strip() for cell in row]
            if any(cleaned_row):
                cleaned.append(cleaned_row)
    return cleaned


def _tables_to_markdown(tables: List[List[List[str]]]) -> str:
    """Convert extracted tables to markdown format for LLM consumption."""
    parts = []
    for idx, table in enumerate(tables):
        if not table:
            continue
        lines = [f"Table {idx + 1}:"]
        # Header
        header = table[0]
        lines.append("| " + " | ".join(header) + " |")
        lines.append("| " + " | ".join("---" for _ in header) + " |")
        # Rows
        for row in table[1:]:
            # Pad row to match header length
            padded = row + [""] * (len(header) - len(row))
            lines.append("| " + " | ".join(padded[:len(header)]) + " |")
        parts.append("\n".join(lines))
    return "\n\n".join(parts)
