from datetime import date
from decimal import Decimal

import pytest

from app.services.csv_parser import CSVParseError, parse_amount, parse_bank_csv


def D(x):
    return Decimal(x)


def test_parse_amount_formats():
    assert parse_amount("$1,234.56") == D("1234.56")
    assert parse_amount("(45.00)") == D("-45.00")
    assert parse_amount("45.00-") == D("-45.00")
    assert parse_amount("-45") == D("-45.00")
    assert parse_amount("\u221245.10") == D("-45.10")          # unicode minus
    assert parse_amount("1.234,56") == D("1234.56")            # European
    assert parse_amount("12,50") == D("12.50")                 # decimal comma
    assert parse_amount("1,23,456.78") == D("123456.78")       # Indian grouping
    assert parse_amount("45.00 DR") == D("-45.00")
    assert parse_amount("45.00CR") == D("45.00")
    assert parse_amount("Rs. 1,200.00") == D("1200.00")
    assert parse_amount("USD 99") == D("99.00")
    assert parse_amount("") is None
    assert parse_amount("n/a") is None
    assert parse_amount("abc") is None
    assert parse_amount("12-34") is None


def test_signed_amount_us_format():
    csv_text = 'Date,Description,Amount,Balance\n01/15/2026,WALMART,"-1,234.56","5,000.00"\n01/16/2026,PAYROLL,3000,8000\n'
    r = parse_bank_csv(csv_text)
    assert r.rows_valid == 2 and not r.errors
    assert list(r.transactions["amount"]) == [D("-1234.56"), D("3000.00")]
    assert list(r.transactions["date"]) == [date(2026, 1, 15), date(2026, 1, 16)]
    assert r.date_format == "%m/%d/%Y"


def test_debit_credit_columns_with_preamble_and_dayfirst_detection():
    csv_text = (
        "Account Statement,,,\nPeriod: 01/09/2026 - 30/09/2026,,,\n,,,\n"
        "Posting Date,Narration,Withdrawal,Deposit\n"
        '01/09/2026,SALARY,,"52,000.00"\n'
        "14/09/2026,SWIGGY,420.50,\n"
    )
    r = parse_bank_csv(csv_text)
    assert r.rows_valid == 2
    assert list(r.transactions["amount"]) == [D("52000.00"), D("-420.50")]
    assert r.transactions["date"].iloc[1] == date(2026, 9, 14)   # 14 can only be a day => DD/MM
    assert r.date_format == "%d/%m/%Y"
    assert any("above the column headers" in w for w in r.warnings)
    assert not any("ambiguous" in w for w in r.warnings)


def test_semicolon_european_file():
    csv_text = "Datum;Beschreibung;Betrag\n05.01.2026;REWE;-12,50\n06.01.2026;GEHALT;2.500,00\n".replace("Datum", "Date").replace("Beschreibung", "Description").replace("Betrag", "Amount")
    r = parse_bank_csv(csv_text)
    assert r.delimiter == ";"
    assert list(r.transactions["amount"]) == [D("-12.50"), D("2500.00")]
    assert r.transactions["date"].iloc[0] == date(2026, 1, 5)


def test_type_column_signs_positive_amounts():
    csv_text = "Date,Description,Amount,Type\n2026-02-01,Rent,1000.00,DR\n2026-02-02,Refund,50.00,CR\n"
    r = parse_bank_csv(csv_text)
    assert list(r.transactions["amount"]) == [D("-1000.00"), D("50.00")]


def test_unrecognised_type_column_is_ignored():
    csv_text = "Date,Description,Amount,Type\n2026-02-01,Shop,-10.00,CARD_PAYMENT\n2026-02-02,Pay,500.00,TRANSFER\n"
    r = parse_bank_csv(csv_text)
    assert list(r.transactions["amount"]) == [D("-10.00"), D("500.00")]


def test_bad_rows_are_reported_not_fatal():
    csv_text = ("Date,Description,Amount\n"
                "2026-03-01,Good,-5.00\n"
                "not-a-date,Bad date,-6.00\n"
                "2026-03-03,Bad amount,abc\n"
                "2026-03-04,Zero,0.00\n"
                ",Total,\n")
    r = parse_bank_csv(csv_text)
    assert r.rows_valid == 1
    assert [e.row for e in r.errors] == [3, 4, 5, 6]
    assert "date" in r.errors[0].reason and "amount" in r.errors[1].reason and "zero" in r.errors[2].reason


def test_fingerprints_distinguish_identical_rows_and_are_stable():
    csv_text = "Date,Description,Amount\n2026-03-01,Coffee,-4.00\n2026-03-01,Coffee,-4.00\n2026-03-02,Coffee,-4.00\n"
    a, b = parse_bank_csv(csv_text), parse_bank_csv(csv_text)
    fp = list(a.transactions["fingerprint"])
    assert len(set(fp)) == 3                      # two same-day coffees stay distinct
    assert fp == list(b.transactions["fingerprint"])  # re-upload => identical => dedupe works


def test_ambiguous_dates_warn_and_respect_dayfirst():
    csv_text = "Date,Description,Amount\n03/04/2026,A,-1\n05/06/2026,B,-2\n"
    r = parse_bank_csv(csv_text)
    assert any("ambiguous" in w for w in r.warnings)
    assert r.transactions["date"].iloc[0] == date(2026, 3, 4)       # month first
    r2 = parse_bank_csv(csv_text, dayfirst=True)
    assert r2.transactions["date"].iloc[0] == date(2026, 4, 3)      # day first
    assert not any("ambiguous" in w for w in r2.warnings)


def test_datetime_and_text_dates():
    r = parse_bank_csv("Date,Description,Amount\n2026-03-01T14:22:10Z,A,-1\n2026-03-02 09:00:00,B,-2\n")
    assert list(r.transactions["date"]) == [date(2026, 3, 1), date(2026, 3, 2)]
    r = parse_bank_csv("Date,Description,Amount\n05 Jan 2026,A,-1\n06 Feb 2026,B,-2\n")
    assert list(r.transactions["date"]) == [date(2026, 1, 5), date(2026, 2, 6)]


def test_invert_sign_and_all_positive_warning():
    csv_text = "Date,Description,Amount\n" + "".join(f"2026-04-0{i},Shop {i},{i * 10}.00\n" for i in range(1, 7))
    r = parse_bank_csv(csv_text)
    assert any("positive" in w for w in r.warnings)
    r2 = parse_bank_csv(csv_text, invert_sign=True)
    assert all(a < 0 for a in r2.transactions["amount"]) and not r2.warnings


def test_encodings():
    cp = "Date,Description,Amount\n2026-01-01,Caf\xe9 Rouge,-4.50\n".encode("cp1252")
    assert parse_bank_csv(cp).transactions["description"].iloc[0] == "Caf\xe9 Rouge"
    bom = "\ufeffDate,Description,Amount\n2026-01-01,X,-1\n".encode("utf-8")
    assert parse_bank_csv(bom).rows_valid == 1
    u16 = "Date,Description,Amount\n2026-01-01,X,-1\n".encode("utf-16")
    assert parse_bank_csv(u16).rows_valid == 1


def test_column_override():
    csv_text = "When,Memo text,How much\n2026-01-01,X,-1\n"
    with pytest.raises(CSVParseError):
        parse_bank_csv(csv_text)
    r = parse_bank_csv(csv_text, column_map={"date": "When", "description": "Memo text", "amount": "How much"})
    assert r.rows_valid == 1


def test_structural_errors():
    with pytest.raises(CSVParseError):
        parse_bank_csv(b"")
    with pytest.raises(CSVParseError):
        parse_bank_csv(b"PK\x03\x04\x00\x00binary")
    with pytest.raises(CSVParseError):
        parse_bank_csv("Foo,Bar\n1,2\n")
    with pytest.raises(CSVParseError):
        parse_bank_csv("Date,Description,Amount\n")
