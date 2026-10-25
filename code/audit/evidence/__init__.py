"""Evidence parsers: one observation per record found in the supplied files."""

from .sql_snapshots import parse_sql_file
from .json_records import parse_json_file
from .logs import parse_log_file
from .documents import parse_pdf_file
from .images import parse_image_file

__all__ = [
    "parse_sql_file",
    "parse_json_file",
    "parse_log_file",
    "parse_pdf_file",
    "parse_image_file",
]
