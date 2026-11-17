from datetime import date

from app import documents
from app.validators import bank, names, tax


def test_known_valid_tax_ids():
    assert tax.validate("IN", "27AAPFU0939F1ZV")["valid"]
    assert tax.validate("DE", "DE136695976")["valid"]
    assert tax.validate("GB", "GB 980 7806 84")["valid"]
    assert tax.validate("US", "12-3456789")["valid"]


def test_tax_problems_are_classified():
    assert tax.validate("IN", "27AAPFU0939F1ZW")["problem"] == "checksum"      # typo
    assert tax.validate("DE", "GB980780684")["problem"] == "jurisdiction"       # other country's ID
    assert tax.validate("US", "07-1234567")["problem"] == "checksum"            # never-issued EIN prefix
    assert tax.validate("GB", "12345")["problem"] == "format"
    assert tax.validate("BR", "123")["problem"] == "unsupported_country"


def test_bank_checksums():
    assert bank.iban_validate("GB82 WEST 1234 5698 7654 32")["valid"]
    assert bank.iban_validate("DE89370400440532013001")["problem"] == "checksum"
    assert bank.iban_validate("GB82WEST123456987654")["problem"] == "length"
    assert bank.aba_validate("021000021")["valid"]
    assert bank.aba_validate("021000022")["problem"] == "checksum"
    assert bank.ifsc_validate("HDFC0001234")["valid"]
    iban = bank.iban_with_check_digits("GB", "BARC20041573849261")
    assert bank.iban_validate(iban)["valid"]


def test_name_matching_verdicts():
    assert names.compare("Northwind Analytics Ltd", "NORTHWIND ANALYTICS LIMITED")["verdict"] == "normalized"
    assert names.compare("Kestrel Logistics Ltd", "Kestral Logistics Ltd")["verdict"] == "near"
    assert names.compare("Helios Solar GmbH", "Helios Energy Holding GmbH")["verdict"] == "related"
    assert names.compare("Apex Industrial Supplies LLC", "Pinnacle Office Products Inc")["verdict"] == "mismatch"
    # generic words alone must not make two companies "related"
    assert names.compare("Global Logistics Ltd", "Global Supplies Ltd")["verdict"] == "mismatch"


def test_dates_and_amounts():
    assert documents.parse_date("03/04/2026", "US") == date(2026, 3, 4)
    assert documents.parse_date("03/04/2026", "GB") == date(2026, 4, 3)
    assert documents.parse_date("13.10.2026", "DE") == date(2026, 10, 13)
    assert documents.parse_date("9 June 2027") == date(2027, 6, 9)
    assert documents.parse_amount("EUR 3.000.000") == 3_000_000
    assert documents.parse_amount("£2,000,000 any one occurrence") == 2_000_000
    assert documents.parse_amount("Rs. 1,50,00,000") == 15_000_000
    assert documents.parse_amount("$1.5m") == 1_500_000
