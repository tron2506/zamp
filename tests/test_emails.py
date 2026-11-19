"""Contact-email checks: real domain endings, look-alike providers, domain vs company name."""
import pytest

from app.validators import emails


@pytest.mark.parametrize("addr,tld_ok,free,lookalike", [
    ("jondoe@gmail.vo", False, False, "gmail.com"),      # not a real ending, and imitates gmail
    ("a@gmail.com", True, True, None),
    ("a@googlemail.com", True, True, None),
    ("a@yahoo.co.uk", True, True, None),                 # legitimate regional domain, not a look-alike
    ("a@gmai1.com", True, False, "gmail.com"),
    ("a@gmail.co", True, False, "gmail.com"),
    ("a@hotmial.com", True, False, "hotmail.com"),       # swapped letters count as one typo
    ("a@outlook-consulting.com", True, False, None),     # a real company that happens to contain a brand word
    ("a@kestrel-logistics.co.uk", True, False, None),
    ("a@studio.design", True, False, None),              # newer real endings are accepted
])
def test_check(addr, tld_ok, free, lookalike):
    c = emails.check(addr)
    assert (c["tld_ok"], c["free"], c["lookalike"]) == (tld_ok, free, lookalike)


def test_related_to_company():
    assert emails.related_to_company("kestrel-logistics.co.uk", ["Kestrel Logistics Ltd"])
    assert emails.related_to_company("ibm.com", ["International Business Machines Corp"])   # initials
    assert emails.related_to_company("mail.orchardvine.co.uk", ["Orchard & Vine Catering Ltd"])
    assert emails.related_to_company("helios-group.de", ["Helios Solar GmbH"])
    assert not emails.related_to_company("acme-trading.io", ["Kestrel Logistics Ltd"])
    assert emails.related_to_company("acme-trading.io", ["Kestrel Logistics Ltd", "Acme Trading"])  # trading name
