"""Bank-statement CSV parser.

Banks all export slightly different CSVs. This module turns any reasonable one into a clean,
validated pandas DataFrame of transactions:

    row | date (datetime.date) | description | amount (Decimal, signed) | fingerprint

Handles: junk lines before the header, , ; TAB | delimiters, UTF-8/BOM/UTF-16/Windows-1252,
one signed Amount column OR separate Debit/Credit columns OR a DR/CR "type" column,
"$1,234.56" / "(45.00)" / "45.00-" / "1.234,56" / "45.00 CR" amounts, and
DD/MM vs MM/DD vs ISO vs "05 Jan 2026" dates (auto-detected per file).

Rows that can't be understood are returned in `errors` with their line number instead of
failing the whole upload. Only structural problems raise CSVParseError.

The module is deliberately independent of Flask and the database so it can be unit-tested
and reused (CLI, background jobs).
"""
from __future__ import annotations

import csv
import hashlib
import io
import re
from collections import Counter
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import IO

import pandas as pd

MAX_ROWS = 50_000
MAX_DESCRIPTION_LEN = 500
MAX_ABS_AMOUNT = Decimal("9999999999.99")  # fits Numeric(12, 2)
_CENT = Decimal("0.01")


class CSVParseError(ValueError):
    """The file as a whole can't be parsed. The message is safe to show to the user."""


@dataclass(frozen=True)
class RowError:
    row: int      # 1-based line number in the uploaded file
    reason: str
    raw: str      # the offending line (truncated)


@dataclass
class ParseResult:
    transactions: pd.DataFrame            # valid rows (see module docstring)
    errors: list[RowError]                # rejected rows
    warnings: list[str]                   # non-fatal things the user should know
    columns: dict[str, str | None]        # logical field -> CSV header that was used
    date_format: str
    delimiter: str
    encoding: str
    rows_total: int                       # non-blank data rows examined

    @property
    def rows_valid(self) -> int:
        return len(self.transactions)

    def summary(self) -> dict:
        tx = self.transactions
        amounts = list(tx["amount"]) if len(tx) else []
        return {
            "rows_total": self.rows_total,
            "rows_valid": self.rows_valid,
            "rows_rejected": len(self.errors),
            "first_date": min(tx["date"]) if len(tx) else None,
            "last_date": max(tx["date"]) if len(tx) else None,
            "money_in": sum((a for a in amounts if a > 0), Decimal("0")),
            "money_out": sum((a for a in amounts if a < 0), Decimal("0")),
        }


# --------------------------------------------------------------------------- headers

# Aliases are normalised (lower-case, punctuation -> single space). Order = priority.
ALIASES: dict[str, tuple[str, ...]] = {
    "date": ("date", "transaction date", "trans date", "txn date", "posted date", "posting date",
             "post date", "date posted", "booking date", "completed date", "value date"),
    "description": ("description", "transaction description", "details", "transaction details",
                    "narrative", "narration", "memo", "payee", "merchant", "particulars", "name",
                    "reference", "remarks"),
    "amount": ("amount", "transaction amount", "amt", "value"),
    "debit": ("debit", "debit amount", "withdrawal", "withdrawals", "withdrawal amount",
              "money out", "paid out", "dr"),
    "credit": ("credit", "credit amount", "deposit", "deposits", "deposit amount",
               "money in", "paid in", "cr"),
    "type": ("type", "transaction type", "dr cr", "cr dr", "debit credit", "credit debit",
             "indicator", "txn type"),
}
_PREFIX_FALLBACK = ("date", "description", "amount", "debit", "credit")  # e.g. "Amount (USD)"


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(text).lower()).strip()


def _resolve_columns(headers: list[str], overrides: dict[str, str] | None = None) -> dict[str, str | None]:
    normed = {h: _norm(h) for h in headers}
    resolved: dict[str, str | None] = {}
    for field, aliases in ALIASES.items():
        if overrides and overrides.get(field):
            wanted = _norm(overrides[field])
            match = next((h for h in headers if normed[h] == wanted), None)
            if match is None:
                raise CSVParseError(f"Column '{overrides[field]}' (for {field}) not found. Columns: {headers}")
            resolved[field] = match
            continue
        match = next((h for alias in aliases for h in headers if normed[h] == alias), None)
        if match is None and field in _PREFIX_FALLBACK:
            match = next((h for h in headers if normed[h].startswith(aliases[0] + " ")), None)
        resolved[field] = match
    return resolved


def _find_header_row(rows: list[list[str]]) -> int | None:
    """Index of the first row that looks like a header (has a date + money column)."""
    for i, row in enumerate(rows[:40]):
        cells = [c.strip() for c in row]
        if sum(1 for c in cells if c) < 2:
            continue
        cols = _resolve_columns(cells)
        if cols["date"] and (cols["amount"] or cols["debit"] or cols["credit"]):
            return i
    return None


# --------------------------------------------------------------------------- text / delimiter

def _read_text(source) -> tuple[str, str]:
    if isinstance(source, str):
        return source, "text"
    raw = source if isinstance(source, (bytes, bytearray)) else source.read()
    if isinstance(raw, str):
        return raw, "text"
    raw = bytes(raw)
    if not raw.strip():
        raise CSVParseError("The file is empty.")
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16"), "utf-16"
    if b"\x00" in raw[:4096]:
        raise CSVParseError("This doesn't look like a text CSV file (binary content detected).")
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1"), "latin-1"


def _detect_delimiter(lines: list[str]) -> str:
    """Pick the delimiter that splits the most lines into the same (>1) number of fields."""
    sample = [ln for ln in lines[:60] if ln.strip()]
    best, best_score = ",", (0, 0)
    for delim in (",", ";", "\t", "|"):
        widths = Counter(len(row) for row in csv.reader(sample, delimiter=delim))
        scored = [(count, width) for width, count in widths.items() if width > 1]
        if scored and max(scored) > best_score:
            best, best_score = delim, max(scored)
    return best


# --------------------------------------------------------------------------- amounts

_EMPTY_TOKENS = {"-", "--", "n/a", "na", "nan", "null", "none"}
_DRCR_SUFFIX = re.compile(r"(?i)(?<![a-z])(cr|dr)\.?\s*$")
_DRCR_PREFIX = re.compile(r"(?i)^\s*(cr|dr)(?![a-z])\.?\s*")


def parse_amount(value) -> Decimal | None:
    """Parse a money string into a signed Decimal (2 dp), or None if blank/invalid.

    '$1,234.56' -> 1234.56   '(45.00)' -> -45.00   '45.00-' -> -45.00   '-45' -> -45.00
    '1.234,56' -> 1234.56    '12,50' -> 12.50       '45.00 DR' -> -45.00  '45.00 CR' -> 45.00
    """
    if value is None:
        return None
    s = str(value).strip().replace("\u2212", "-").replace("\u2013", "-")
    if not s or s.lower() in _EMPTY_TOKENS:
        return None

    negative = False
    marker = _DRCR_SUFFIX.search(s) or _DRCR_PREFIX.match(s)
    if marker:
        negative = marker.group(1).lower() == "dr"
        s = (s[: marker.start()] + s[marker.end():]).strip()
    if s.startswith("(") and s.endswith(")"):
        negative, s = True, s[1:-1]

    s = re.sub(r"[A-Za-z]+\.?", "", s)       # currency words: USD, Rs.
    s = re.sub(r"[^\d.,\-]", "", s)          # symbols, spaces, apostrophes
    if s.startswith("-"):
        negative, s = True, s[1:]
    elif s.endswith("-"):
        negative, s = True, s[:-1]
    if "-" in s or not re.search(r"\d", s):
        return None

    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):      # European: 1.234,56
            s = s.replace(".", "").replace(",", ".")
        else:                                # US/Indian: 1,234.56 / 1,23,456.78
            s = s.replace(",", "")
    elif "," in s:
        head, _, tail = s.rpartition(",")
        if len(tail) in (1, 2) and "," not in head:   # decimal comma: 12,5 / 45,00
            s = f"{head}.{tail}"
        else:                                          # thousands: 1,234 / 1,234,567
            s = s.replace(",", "")
    elif s.count(".") > 1:                   # 1.234.567 (thousands dots)
        s = s.replace(".", "")

    try:
        number = Decimal(s).quantize(_CENT, rounding=ROUND_HALF_UP)
    except InvalidOperation:
        return None
    return -number if negative else number


_DEBIT_WORDS = {"debit", "dr", "d", "db", "withdrawal", "withdraw"}
_CREDIT_WORDS = {"credit", "cr", "c", "deposit"}


def _type_sign(value: str) -> int:
    word = _norm(value)
    return -1 if word in _DEBIT_WORDS else 1 if word in _CREDIT_WORDS else 0


def _apply_type_column(amounts: list[Decimal | None], types: list[str]) -> tuple[list[Decimal | None], bool]:
    """Use a Debit/Credit indicator column to sign the amounts. Ignored unless it is
    clearly a DR/CR column (>=50% of its values recognised), e.g. Chase's CARD_PAYMENT types."""
    signs = [_type_sign(t) for t in types]
    filled = sum(1 for t in types if str(t).strip())
    if not filled or sum(1 for s in signs if s) / filled < 0.5:
        return amounts, False
    out = [None if a is None else (a if s == 0 else -abs(a) if s < 0 else abs(a)) for a, s in zip(amounts, signs)]
    return out, True


def _combine(debit: Decimal | None, credit: Decimal | None) -> Decimal | None:
    if debit is None and credit is None:
        return None
    return abs(credit or Decimal(0)) - abs(debit or Decimal(0))


# --------------------------------------------------------------------------- dates

_TIME_SUFFIX = r"[\sT]+\d{1,2}:\d{2}(?::\d{2}(?:\.\d+)?)?\s*(?:[AaPp][Mm])?\s*(?:Z|[+-]\d{2}:?\d{2})?$"
_ISO = ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y%m%d")
_DMY = ("%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%y", "%d-%m-%y", "%d.%m.%y")
_MDY = ("%m/%d/%Y", "%m-%d-%Y", "%m/%d/%y", "%m-%d-%y")
_TEXT = ("%d %b %Y", "%d-%b-%Y", "%d %B %Y", "%b %d, %Y", "%b %d %Y", "%B %d, %Y", "%d %b %y", "%d-%b-%y")


def _swap_day_month(fmt: str) -> str | None:
    if "%d" in fmt and "%m" in fmt:
        return fmt.replace("%d", "\0").replace("%m", "%d").replace("\0", "%m")
    return None


def _parse_dates(raw: pd.Series, dayfirst: bool | None) -> tuple[pd.Series, str, bool]:
    """Parse a column of date strings using the single format that fits the most rows.

    Returns (datetime Series, format, ambiguous). `ambiguous` means DD/MM and MM/DD both fit
    every row equally well; `dayfirst` (default False) then decides.
    """
    cleaned = raw.astype(str).str.strip().str.replace(_TIME_SUFFIX, "", regex=True)
    non_empty = int((cleaned != "").sum())
    formats = _ISO + (_DMY + _MDY if dayfirst else _MDY + _DMY) + _TEXT

    best_fmt, best, best_n = "", None, -1
    for fmt in formats:
        parsed = pd.to_datetime(cleaned, format=fmt, errors="coerce")
        n = int(parsed.notna().sum())
        if n > best_n:
            best_fmt, best, best_n = fmt, parsed, n
        if n == non_empty:
            break
    if best_n <= 0:
        raise CSVParseError("Couldn't recognise the date format in the date column.")

    swapped = _swap_day_month(best_fmt)
    ambiguous = False
    if swapped and dayfirst is None and best_fmt in _DMY + _MDY:  # ISO (Y-M-D) is never ambiguous
        ambiguous = int(pd.to_datetime(cleaned, format=swapped, errors="coerce").notna().sum()) == best_n
    return best, best_fmt, ambiguous


# --------------------------------------------------------------------------- main entry point

def _dedupe_headers(cells: list[str]) -> list[str]:
    seen: Counter = Counter()
    out = []
    for i, cell in enumerate(cells):
        name = cell.strip() or f"column_{i + 1}"
        seen[name] += 1
        out.append(name if seen[name] == 1 else f"{name}_{seen[name]}")
    return out


def _clean_description(value: str) -> str:
    return re.sub(r"\s+", " ", str(value)).strip()[:MAX_DESCRIPTION_LEN] or "(no description)"


def _raw(row: list[str]) -> str:
    return " | ".join(c.strip() for c in row)[:200]


def parse_bank_csv(
    source: bytes | str | IO,
    *,
    dayfirst: bool | None = None,
    invert_sign: bool = False,
    column_map: dict[str, str] | None = None,
    max_rows: int = MAX_ROWS,
) -> ParseResult:
    """Parse an uploaded bank CSV (bytes, text, or a file-like object such as werkzeug's FileStorage).

    dayfirst     Preferred day/month order when dates are ambiguous (None => month first + warning).
    invert_sign  Flip all signs. Use for credit-card exports where purchases are positive.
    column_map   Manual override {"date": "Posted On", "description": "Memo", "amount": "Amt"}
                 (also "debit", "credit", "type") using the CSV's own header names.
    """
    text, encoding = _read_text(source)
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if not any(ln.strip() for ln in lines):
        raise CSVParseError("The file is empty.")

    delimiter = _detect_delimiter(lines)
    warnings: list[str] = []

    header_idx = _find_header_row(list(csv.reader(lines[:40], delimiter=delimiter)))
    if header_idx is None:
        header_idx = next(i for i, ln in enumerate(lines) if ln.strip())
    elif header_idx > 0:
        warnings.append(f"Ignored {header_idx} line(s) above the column headers.")

    # --- tokenise rows (csv handles quotes; we keep exact line numbers for error reports)
    reader = csv.reader(lines[header_idx:], delimiter=delimiter)
    headers = _dedupe_headers(next(reader))
    width = len(headers)
    rows: list[list[str]] = []
    line_numbers: list[int] = []
    row_errors: list[RowError] = []
    rows_total = 0
    for row in reader:
        if not any(c.strip() for c in row):
            continue
        line_no = header_idx + reader.line_num
        rows_total += 1
        if rows_total > max_rows:
            raise CSVParseError(f"Too many rows (limit is {max_rows:,}). Split the statement into smaller files.")
        if len(row) > width and any(c.strip() for c in row[width:]):
            row_errors.append(RowError(line_no, "more columns than the header", _raw(row)))
            continue
        rows.append((row + [""] * width)[:width])
        line_numbers.append(line_no)
    if rows_total == 0:
        raise CSVParseError("No transaction rows found below the header.")

    # --- map columns
    cols = _resolve_columns(headers, column_map)
    if not cols["date"]:
        raise CSVParseError(f"Couldn't find a date column. Columns found: {', '.join(headers)}")
    if not cols["description"]:
        raise CSVParseError(f"Couldn't find a description column. Columns found: {', '.join(headers)}")
    if not (cols["amount"] or cols["debit"] or cols["credit"]):
        raise CSVParseError(f"Couldn't find an amount (or debit/credit) column. Columns found: {', '.join(headers)}")

    df = pd.DataFrame(rows, columns=headers, dtype=object) if rows else pd.DataFrame(columns=headers)

    # --- dates
    if rows:
        dates, date_format, ambiguous = _parse_dates(df[cols["date"]], dayfirst)
        if ambiguous:
            warnings.append("Dates like 03/04/2026 are ambiguous; they were read as MM/DD/YYYY. "
                            "If your bank uses DD/MM/YYYY, re-upload with the day-first option.")
    else:
        dates, date_format = pd.Series(dtype="datetime64[ns]"), ""

    # --- amounts
    type_applied = False
    if cols["amount"]:
        amounts = [parse_amount(v) for v in df[cols["amount"]]]
        if cols["type"]:
            amounts, type_applied = _apply_type_column(amounts, list(df[cols["type"]]))
    else:
        debits = [parse_amount(v) for v in df[cols["debit"]]] if cols["debit"] else [None] * len(df)
        credits = [parse_amount(v) for v in df[cols["credit"]]] if cols["credit"] else [None] * len(df)
        amounts = [_combine(d, c) for d, c in zip(debits, credits)]
    if invert_sign:
        amounts = [None if a is None else -a for a in amounts]

    valid_amounts = [a for a in amounts if a]
    if (cols["amount"] and not type_applied and not invert_sign
            and len(valid_amounts) >= 5 and all(a > 0 for a in valid_amounts)):
        warnings.append("Every amount is positive, so all rows were treated as income. If this is a credit-card "
                        "export where purchases are positive, re-upload with 'positive amounts are expenses'.")

    # --- assemble valid rows, reject bad ones
    descriptions = [_clean_description(v) for v in df[cols["description"]]]
    errors = list(row_errors)
    occurrences: Counter = Counter()
    records = []
    for i, (line_no, raw_row) in enumerate(zip(line_numbers, rows)):
        parsed_date, amount = dates.iloc[i], amounts[i]
        problems = []
        if pd.isna(parsed_date):
            problems.append("invalid or missing date")
        if amount is None:
            problems.append("invalid or missing amount")
        elif amount == 0:
            problems.append("zero amount")
        elif abs(amount) > MAX_ABS_AMOUNT:
            problems.append("amount out of range")
        if problems:
            errors.append(RowError(line_no, "; ".join(problems), _raw(raw_row)))
            continue

        day = parsed_date.date()
        # Fingerprint = identity of the transaction. The occurrence counter keeps two genuinely
        # identical purchases on one day distinct, while re-uploading the file reproduces the
        # same fingerprints (=> duplicates are skipped by the DB unique constraint).
        key = f"{day.isoformat()}|{amount:.2f}|{descriptions[i].lower()}"
        n = occurrences[key]
        occurrences[key] += 1
        fingerprint = hashlib.sha256(f"{key}|{n}".encode()).hexdigest()
        records.append((line_no, day, descriptions[i], amount, fingerprint))

    errors.sort(key=lambda e: e.row)
    transactions = pd.DataFrame(records, columns=["row", "date", "description", "amount", "fingerprint"])
    return ParseResult(
        transactions=transactions, errors=errors, warnings=warnings, columns=cols,
        date_format=date_format, delimiter=delimiter, encoding=encoding, rows_total=rows_total,
    )
