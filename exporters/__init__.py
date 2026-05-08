from __future__ import annotations

from .json_exp import to_json
from .markdown_exp import to_markdown
from .csv_exp import to_csv
from .xlsx_exp import to_xlsx
from .pdf_exp import to_pdf

EXPORTERS = {
    "json": (to_json, "application/json", "json"),
    "md":   (to_markdown, "text/markdown", "md"),
    "csv":  (to_csv, "text/csv", "csv"),
    "xlsx": (to_xlsx, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"),
    "pdf":  (to_pdf, "application/pdf", "pdf"),
}

__all__ = ["EXPORTERS", "to_json", "to_markdown", "to_csv", "to_xlsx", "to_pdf"]
