"""Realistic test inputs: vendor submissions + generated PDF documents, plus a seeded vendor master.

Dates are generated relative to *today* so that "expired" and "valid" stay true whenever you run it.
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from . import config, db
from .validators import bank, tax

T = date.today()


def d(days: int) -> date:
    return T + timedelta(days=days)


def uk(dt: date) -> str:
    return dt.strftime("%d %B %Y").lstrip("0")


def us(dt: date) -> str:
    return dt.strftime("%m/%d/%Y")


def de(dt: date) -> str:
    return dt.strftime("%d.%m.%Y")


def iso(dt: date) -> str:
    return dt.isoformat()


# ------------------------------------------------------------------ valid identifiers
GB_VAT_NORTHWIND = "GB2837461" + tax.gb_vat_check_digits("2837461")
GB_VAT_KESTREL = "GB6620193" + tax.gb_vat_check_digits("6620193")
GB_VAT_LUMEN = "GB4451027" + tax.gb_vat_check_digits("4451027")
DE_VAT_HELIOS = "DE81457302" + str(tax.de_vat_check_digit("81457302"))
_g14 = "29AAKCB4821M1Z"
GSTIN_BRIGHTPATH = _g14 + tax.gstin_check_char(_g14)
GSTIN_TYPO = GSTIN_BRIGHTPATH[:9] + "2" + GSTIN_BRIGHTPATH[10:] if GSTIN_BRIGHTPATH[9] != "2" else GSTIN_BRIGHTPATH[:9] + "3" + GSTIN_BRIGHTPATH[10:]
EIN_COBALT, EIN_SUMMIT, EIN_APEX, EIN_PINNACLE = "84-3920175", "61-2209384", "47-1185290", "26-4417733"

IBAN_NORTHWIND = bank.iban_with_check_digits("GB", "BARC20041573849261")
IBAN_KESTREL = bank.iban_with_check_digits("GB", "NWBK60161331926819")
IBAN_KESTREL_NEW = bank.iban_with_check_digits("GB", "MONZ04000477129903")
IBAN_LUMEN = bank.iban_with_check_digits("GB", "HBUK40127691834577")
IBAN_HELIOS = bank.iban_with_check_digits("DE", "370400440532013991")
IBAN_ORCHARD = bank.iban_with_check_digits("GB", "LOYD30995582014467")
GB_VAT_ORCHARD = "GB5839207" + tax.gb_vat_check_digits("5839207")
IBAN_ORION = bank.iban_with_check_digits("GB", "LOYD30963910482736")
ABA_CHASE, ABA_BOFA = "021000021", "026009593"
ACCT_PINNACLE = "483920175566"


# ------------------------------------------------------------------ PDF rendering
def pdf(path: Path, org: str, title: str, lines: list[str], accent=colors.HexColor("#1f4e79"), sub: str = "",
        footer: str = ""):
    c = canvas.Canvas(str(path), pagesize=A4)
    w, h = A4
    c.setFillColor(accent)
    c.rect(0, h - 70, w, 70, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(40, h - 42, org)
    if sub:
        c.setFont("Helvetica", 9)
        c.drawString(40, h - 58, sub)
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 14)
    c.drawString(40, h - 110, title)
    y = h - 145
    for ln in lines:
        if ln == "":
            y -= 10
            continue
        if ln.startswith("##"):
            c.setFont("Helvetica-Bold", 11)
            c.drawString(40, y, ln[2:].strip())
        elif ":" in ln and not ln.startswith(" "):
            k, v = ln.split(":", 1)
            c.setFont("Helvetica-Bold", 10)
            c.drawString(40, y, k + ":")
            c.setFont("Helvetica", 10)
            c.drawString(230, y, v.strip())
        else:
            c.setFont("Helvetica", 10)
            c.drawString(40, y, ln.strip())
        y -= 17
    c.setFont("Helvetica-Oblique", 8)
    c.setFillColor(colors.grey)
    c.drawString(40, 40, footer or f"Document generated for vendor onboarding test data · {T.isoformat()}")
    c.save()


def hmrc_vat(path, name, vat, addr, reg_date):
    pdf(path, "HM Revenue & Customs", "VAT Registration Certificate", [
        "This certificate confirms registration for Value Added Tax.", "",
        f"VAT registration number: {vat[2:5]} {vat[5:9]} {vat[9:]}",
        f"Name: {name}", f"Address: {addr}",
        f"Effective date of registration: {uk(reg_date)}", f"Date of issue: {uk(reg_date + timedelta(days=9))}", "",
        "Keep this certificate in a safe place. You must show your VAT number on all invoices.",
    ], accent=colors.HexColor("#00703c"), sub="VAT Registration Service, BX9 1WR")


def bzst_vat(path, name, vat, addr, issued):
    pdf(path, "Bundeszentralamt für Steuern", "Bestätigung der Umsatzsteuer-Identifikationsnummer", [
        "Confirmation of VAT identification number (USt-IdNr) / Umsatzsteuer", "",
        f"Registered name: {name}", f"USt-IdNr: {vat}", f"Address: {addr}", f"Date of issue: {de(issued)}", "",
        "Diese Bestätigung wurde maschinell erstellt.",
    ], accent=colors.HexColor("#000000"), sub="Dienstsitz Saarlouis · 66738 Saarlouis")


def gst_reg06(path, name, gstin, addr, reg):
    pdf(path, "Government of India", "Form GST REG-06 — Registration Certificate", [
        "Goods and Services Tax", "", f"GSTIN: {gstin}", f"Legal Name of Business: {name}",
        "Constitution of Business: Private Limited Company", f"Address: {addr}",
        f"Date of Liability: {reg.strftime('%d/%m/%Y')}", f"Date of issue: {(reg + timedelta(days=4)).strftime('%d/%m/%Y')}",
        "", "This is a system generated digitally signed Registration Certificate.",
    ], accent=colors.HexColor("#ff6f00"), sub="Goods and Services Tax Network")


def w9(path, name, ein, addr, signed):
    pdf(path, "Form W-9 (Rev. March 2024)", "Request for Taxpayer Identification Number and Certification", [
        "Department of the Treasury — Internal Revenue Service", "",
        f"Name (as shown on your income tax return): {name}", "Federal tax classification: C Corporation",
        f"Address: {addr}", "##Part I — Taxpayer Identification Number (TIN)",
        f"Employer identification number: {ein}", "", "##Part II — Certification",
        "Under penalties of perjury, I certify that the number shown on this form is my correct TIN.",
        f"Signed on: {us(signed)}",
    ], accent=colors.HexColor("#3a3a3a"), sub="Give form to the requester. Do not send to the IRS.")


def bank_letter_iban(path, bank_name, holder, iban, bic, dated, label="Account Holder", german=False):
    lines = [
        "To whom it may concern," if not german else "Sehr geehrte Damen und Herren / To whom it may concern,", "",
        "This is to confirm that the following account is held with us and is in good standing.", "",
        f"{label}: {holder}", f"IBAN: {' '.join(iban[i:i + 4] for i in range(0, len(iban), 4))}", f"BIC: {bic}",
        f"Bank name: {bank_name}", "Account currency: " + ("EUR" if iban.startswith("DE") else "GBP"),
        f"Date: {de(dated) if german else uk(dated)}", "", "Yours faithfully,", "Business Banking Operations",
    ]
    pdf(path, bank_name, "Bank Confirmation Letter", lines, accent=colors.HexColor("#00395d"))


def bank_letter_us(path, bank_name, holder, routing, acct, dated):
    pdf(path, bank_name, "Bank Account Verification Letter", [
        "RE: Account confirmation — bank letter", "",
        "This letter is to confirm that the account below is open and active with our institution.", "",
        f"Name on account: {holder}", f"Account number: {acct}", f"ABA routing number: {routing}",
        "Account type: Business Checking", f"Bank name: {bank_name}", f"Date: {us(dated)}", "",
        "Sincerely,", "Commercial Banking Services",
    ], accent=colors.HexColor("#117aca"))


def bank_letter_in(path, bank_name, holder, ifsc, acct, dated):
    pdf(path, bank_name, "Bank Confirmation Letter", [
        "TO WHOMSOEVER IT MAY CONCERN", "", "This is to confirm that the account details given below are correct.", "",
        f"Account Name: {holder}", f"Account Number: {acct}", f"IFSC Code: {ifsc}", "Account Type: Current Account",
        f"Bank name: {bank_name}", f"Date: {dated.strftime('%d/%m/%Y')}", "", "Branch Manager",
    ], accent=colors.HexColor("#004c8f"))


def bank_letter_narrative(path, holder, iban, bic, dated):
    """A real-world style letter: prose only, no 'Label: value' lines. Rules can't parse it; the LLM can."""
    spaced = " ".join(iban[i:i + 4] for i in range(0, len(iban), 4))
    pdf(path, "Lloyds Bank plc", "Account Confirmation", [
        "Dear Sir or Madam,", "",
        f"We are pleased to confirm that {holder} has held a business current",
        "account with Lloyds Bank since March 2019 and that the account is in good standing.", "",
        "Payments to our customer should be made to the following account.",
        f"    {spaced}   (BIC {bic})", "",
        "This confirmation is given in strict confidence and without responsibility on the part of the bank.",
        f"Issued at our Bristol business centre on {uk(dated)}.", "", "Yours faithfully,", "Relationship Manager, Commercial Banking",
    ], accent=colors.HexColor("#006a4d"))


def insurance_uk(path, insurer, insured, policy, cover, start, end):
    pdf(path, insurer, "Certificate of Insurance — Public & Products Liability", [
        f"Policyholder: {insured}", f"Policy number: {policy}", f"Insurer: {insurer}",
        f"Period of Insurance: {uk(start)} to {uk(end)}", f"Limit of liability: {cover} any one occurrence",
        "", "This certificate is evidence of cover only and does not amend the policy terms.",
    ], accent=colors.HexColor("#5b2c83"))


def insurance_de(path, insurer, insured, policy, cover, start, end):
    pdf(path, insurer, "Versicherungsbestätigung / Certificate of Insurance", [
        "Betriebshaftpflichtversicherung (General Liability)", "",
        f"Insured: {insured}", f"Policy number: {policy}", f"Insurer: {insurer}",
        f"Valid from: {de(start)}", f"Valid until: {de(end)}", f"Coverage limit: {cover}",
    ], accent=colors.HexColor("#003781"))


def insurance_acord(path, insurer, insured, policy, cover, start, end):
    pdf(path, "ACORD-style certificate", "Certificate of Liability Insurance", [
        "THIS CERTIFICATE IS ISSUED AS A MATTER OF INFORMATION ONLY.", "",
        f"Named Insured: {insured}", f"Insurer A: {insurer}", "Type of insurance: Commercial General Liability",
        f"Policy number: {policy}", f"Policy effective date: {us(start)}", f"Policy expiration date: {us(end)}",
        f"Each occurrence: {cover}", "General aggregate: $4,000,000",
    ], accent=colors.HexColor("#7a1f1f"))


def insurance_in(path, insurer, insured, policy, cover, start, end):
    pdf(path, insurer, "Certificate of Insurance — Commercial General Liability", [
        f"Insured: {insured}", f"Policy No.: {policy}", f"Insurer: {insurer}",
        f"Period of Insurance: {start.strftime('%d/%m/%Y')} to {end.strftime('%d/%m/%Y')}",
        f"Limit of liability: {cover}",
    ], accent=colors.HexColor("#8a1538"))


def companies_house(path, name, number, inc):
    pdf(path, "Companies House", "Certificate of Incorporation of a Private Limited Company", [
        f"Company number: {number}", "",
        "The Registrar of Companies for England and Wales hereby certifies that", f"Company name: {name}",
        "is this day incorporated under the Companies Act 2006 as a private company, that the company is limited by shares.",
        f"Date of incorporation: {uk(inc)}",
    ], accent=colors.HexColor("#0b0c0c"))


# ------------------------------------------------------------------ scenarios
def _base_gb(**kw):
    s = {"entity_type": "company", "country": "United Kingdom", "bank_name": "Barclays Bank UK PLC"}
    s.update(kw)
    return s


SCENARIOS: list[dict] = []


def scenario(key, title, expected, edge, description):
    def wrap(fn):
        SCENARIOS.append({"key": key, "title": title, "expected": expected, "edge": edge,
                          "description": description, "build": fn})
        return fn
    return wrap


@scenario("northwind_happy", "Northwind Analytics — clean submission", "APPROVED", "Happy path",
          "UK analytics firm; every field, document and cross-check lines up.")
def _(p: Path):
    s = _base_gb(legal_name="Northwind Analytics Ltd", address="14 Hanover Square, London W1S 1HN",
                 website="https://www.northwind-analytics.co.uk", contact_name="Priya Shah",
                 contact_email="priya.shah@northwind-analytics.co.uk", contact_phone="+44 20 7946 0321",
                 tax_id=GB_VAT_NORTHWIND, iban=IBAN_NORTHWIND, bic="BARCGB22", account_holder="Northwind Analytics Ltd")
    hmrc_vat(p / "vat_certificate.pdf", "NORTHWIND ANALYTICS LIMITED", GB_VAT_NORTHWIND, s["address"], d(-900))
    bank_letter_iban(p / "barclays_letter.pdf", "Barclays Bank UK PLC", "Northwind Analytics Limited", IBAN_NORTHWIND,
                     "BARCGB22", d(-21))
    insurance_uk(p / "hiscox_certificate.pdf", "Hiscox Insurance Company Ltd", "Northwind Analytics Ltd", "PL-7731904",
                 "£2,000,000", d(-160), d(205))
    companies_house(p / "certificate_of_incorporation.pdf", "NORTHWIND ANALYTICS LTD", "11839204", d(-2300))
    return s, {"tax_certificate": "vat_certificate.pdf", "bank_letter": "barclays_letter.pdf",
               "insurance_certificate": "hiscox_certificate.pdf", "incorporation_certificate": "certificate_of_incorporation.pdf"}


def _helios(p: Path, parent=None):
    s = {"entity_type": "company", "legal_name": "Helios Solar GmbH", "country": "Germany",
         "address": "Friedrichstraße 88, 10117 Berlin", "website": "helios-solar.de", "contact_name": "Jonas Weber",
         "contact_email": "j.weber@helios-solar.de", "contact_phone": "+49 30 2209 5541", "tax_id": DE_VAT_HELIOS,
         "bank_name": "Commerzbank AG", "iban": IBAN_HELIOS, "bic": "COBADEFFXXX", "account_holder": "Helios Solar GmbH"}
    if parent:
        s["parent_company"] = parent
    bzst_vat(p / "ust_idnr_bestaetigung.pdf", "Helios Solar GmbH", DE_VAT_HELIOS, s["address"], d(-400))
    bank_letter_iban(p / "commerzbank_bestaetigung.pdf", "Commerzbank AG", "Helios Energy Holding GmbH", IBAN_HELIOS,
                     "COBADEFFXXX", d(-35), label="Account holder / Kontoinhaber", german=True)
    insurance_de(p / "allianz_versicherung.pdf", "Allianz Versicherungs-AG", "Helios Solar GmbH", "BH-55-2093871",
                 "EUR 3.000.000", d(-90), d(275))
    return s, {"tax_certificate": "ust_idnr_bestaetigung.pdf", "bank_letter": "commerzbank_bestaetigung.pdf",
               "insurance_certificate": "allianz_versicherung.pdf"}


@scenario("helios_related_holder", "Helios Solar — bank account in parent's name", "PENDING", "Edge 1 · Bank name mismatch",
          "Bank letter names 'Helios Energy Holding GmbH'. Related, not identical → ask for third-party payment authorisation.")
def _(p: Path):
    return _helios(p)


@scenario("helios_declared_parent", "Helios Solar — parent declared up-front", "APPROVED", "Edge 1 · Bank name mismatch",
          "Same documents, but the vendor declared the parent company on the form → accepted with an audit note.")
def _(p: Path):
    return _helios(p, parent="Helios Energy Holding GmbH")


@scenario("brightpath_gstin_typo", "Brightpath Consulting — GSTIN typo", "PENDING", "Edge 2 · Tax ID vs country",
          "One character of the GSTIN mistyped on the form; the certificate holds the valid one → treated as a typo, not fraud.")
def _(p: Path):
    s = {"entity_type": "company", "legal_name": "Brightpath Consulting Pvt Ltd", "country": "India",
         "address": "4th Floor, Prestige Tower, MG Road, Bengaluru 560001", "website": "brightpath.in",
         "contact_name": "Ananya Rao", "contact_email": "ananya@brightpath.in", "contact_phone": "+91 80 4110 2290",
         "tax_id": GSTIN_TYPO, "bank_name": "HDFC Bank Ltd", "ifsc": "HDFC0001234", "account_number": "50200061784421",
         "account_holder": "Brightpath Consulting Pvt Ltd"}
    gst_reg06(p / "gst_reg06.pdf", "BRIGHTPATH CONSULTING PRIVATE LIMITED", GSTIN_BRIGHTPATH, s["address"], d(-1200))
    bank_letter_in(p / "hdfc_letter.pdf", "HDFC Bank Ltd", "BRIGHTPATH CONSULTING PVT LTD", "HDFC0001234",
                   "50200061784421", d(-12))
    insurance_in(p / "icici_lombard_cgl.pdf", "ICICI Lombard General Insurance", "Brightpath Consulting Pvt Ltd",
                 "4001/CGL/228814", "Rs. 1,50,00,000", d(-30), d(335))
    return s, {"tax_certificate": "gst_reg06.pdf", "bank_letter": "hdfc_letter.pdf", "insurance_certificate": "icici_lombard_cgl.pdf"}


@scenario("lumen_wrong_jurisdiction", "Lumen Design — German company, UK tax ID & bank", "PENDING", "Edge 2 · Tax ID vs country",
          "Claims Germany but supplies a valid GB VAT number and a GB IBAN — a jurisdiction mismatch, not a typo.")
def _(p: Path):
    s = {"entity_type": "company", "legal_name": "Lumen Design GmbH", "country": "DE",
         "address": "Hohenzollernring 21, 50672 Köln", "website": "lumendesign.de", "contact_name": "Clara Schmidt",
         "contact_email": "clara@lumendesign.de", "contact_phone": "+49 221 9874 113", "tax_id": GB_VAT_LUMEN,
         "bank_name": "HSBC UK Bank plc", "iban": IBAN_LUMEN, "bic": "HBUKGB4B", "account_holder": "Lumen Design GmbH"}
    hmrc_vat(p / "vat_certificate.pdf", "LUMEN DESIGN LTD", GB_VAT_LUMEN, "71 Shoreditch High St, London E1 6JJ", d(-500))
    bank_letter_iban(p / "hsbc_letter.pdf", "HSBC UK Bank plc", "Lumen Design GmbH", IBAN_LUMEN, "HBUKGB4B", d(-40))
    insurance_de(p / "ergo_versicherung.pdf", "ERGO Versicherung AG", "Lumen Design GmbH", "HV-1182-77", "EUR 1.500.000",
                 d(-120), d(245))
    return s, {"tax_certificate": "vat_certificate.pdf", "bank_letter": "hsbc_letter.pdf", "insurance_certificate": "ergo_versicherung.pdf"}


@scenario("cobalt_bad_documents", "Cobalt Freight — expired insurance, someone else's W-9", "PENDING",
          "Edge 3 · Expired / wrong document",
          "Insurance lapsed last month and the W-9 uploaded belongs to a different company. Each gets a specific request.")
def _(p: Path):
    s = {"entity_type": "company", "legal_name": "Cobalt Freight Inc", "country": "US",
         "address": "2200 Commerce St, Dallas, TX 75201", "website": "cobaltfreight.com", "contact_name": "Marcus Lee",
         "contact_email": "mlee@cobaltfreight.com", "contact_phone": "+1 214 555 0187", "tax_id": EIN_COBALT,
         "bank_name": "Bank of America, N.A.", "routing_number": ABA_BOFA, "account_number": "3849201177",
         "account_holder": "Cobalt Freight Inc"}
    w9(p / "w9.pdf", "Summit Paper Co", EIN_SUMMIT, "80 Industrial Way, Akron, OH 44308", d(-60))
    bank_letter_us(p / "boa_letter.pdf", "Bank of America, N.A.", "COBALT FREIGHT INC", ABA_BOFA, "3849201177", d(-15))
    insurance_acord(p / "coi_2025.pdf", "Travelers Casualty and Surety Co", "Cobalt Freight Inc", "CGL-6620915",
                    "$2,000,000", d(-399), d(-34))
    return s, {"tax_certificate": "w9.pdf", "bank_letter": "boa_letter.pdf", "insurance_certificate": "coi_2025.pdf"}


@scenario("apex_shared_account", "Apex Industrial — bank account belongs to another vendor", "REJECTED",
          "Edge 4 · Fraud signal",
          "Every document looks perfect on its own. Only cross-referencing the vendor master reveals the account is Pinnacle's.")
def _(p: Path):
    s = {"entity_type": "company", "legal_name": "Apex Industrial Supplies LLC", "country": "US",
         "address": "515 W Monroe St, Chicago, IL 60661", "website": "apexindustrial.com", "contact_name": "Dana Brooks",
         "contact_email": "dana.brooks@apexindustrial.com", "contact_phone": "+1 312 555 0144", "tax_id": EIN_APEX,
         "bank_name": "JPMorgan Chase Bank, N.A.", "routing_number": ABA_CHASE, "account_number": ACCT_PINNACLE,
         "account_holder": "Apex Industrial Supplies LLC"}
    w9(p / "w9_apex.pdf", "Apex Industrial Supplies LLC", EIN_APEX, s["address"], d(-10))
    bank_letter_us(p / "chase_letter.pdf", "JPMorgan Chase Bank, N.A.", "Apex Industrial Supplies LLC", ABA_CHASE,
                   ACCT_PINNACLE, d(-8))
    insurance_acord(p / "coi_apex.pdf", "Liberty Mutual Insurance", "Apex Industrial Supplies LLC", "TB2-641-8820",
                    "$1,000,000", d(-50), d(315))
    return s, {"tax_certificate": "w9_apex.pdf", "bank_letter": "chase_letter.pdf", "insurance_certificate": "coi_apex.pdf"}


@scenario("orchard_narrative_letter", "Orchard & Vine — bank letter written as prose", "APPROVED",
          "AI assist · Messy document",
          "The bank letter has no labelled fields. Rules alone can't read the account holder (→ held for review); "
          "with AI assist the holder and IBAN are extracted, verified against the text, and the vendor is approved.")
def _(p: Path):
    s = _base_gb(legal_name="Orchard & Vine Catering Ltd", address="3 Wapping Wharf, Bristol BS1 6WP",
                 website="orchardvine.co.uk", contact_name="Hannah Price", contact_email="hannah@orchardvine.co.uk",
                 contact_phone="+44 117 496 0812", tax_id=GB_VAT_ORCHARD, bank_name="Lloyds Bank plc",
                 iban=IBAN_ORCHARD, bic="LOYDGB21", account_holder="Orchard & Vine Catering Ltd")
    hmrc_vat(p / "vat_certificate.pdf", "ORCHARD & VINE CATERING LTD", GB_VAT_ORCHARD, s["address"], d(-700))
    bank_letter_narrative(p / "lloyds_confirmation.pdf", "Orchard & Vine Catering Ltd", IBAN_ORCHARD, "LOYDGB21", d(-9))
    insurance_uk(p / "insurance_certificate.pdf", "Aviva Insurance Ltd", "Orchard & Vine Catering Ltd", "AV-PL-3390127",
                 "£2,000,000", d(-100), d(265))
    return s, {"tax_certificate": "vat_certificate.pdf", "bank_letter": "lloyds_confirmation.pdf",
               "insurance_certificate": "insurance_certificate.pdf"}


_RULES_ONLY_EXPECTED = {"orchard_narrative_letter": "PENDING"}


def expected(meta: dict, llm_on: bool) -> str:
    return meta["expected"] if llm_on else _RULES_ONLY_EXPECTED.get(meta["key"], meta["expected"])


def _kestrel(p: Path, phone=True, insurance=True, iban=IBAN_KESTREL, email="tom.hughes@kestrel-logistics.co.uk",
             bank_name="National Westminster Bank plc", bic="NWBKGB2L"):
    s = _base_gb(legal_name="Kestrel Logistics Ltd", address="Unit 7, Trafford Park, Manchester M17 1HH",
                 website="kestrel-logistics.co.uk", contact_name="Tom Hughes", contact_email=email,
                 contact_phone="+44 161 496 0750" if phone else "", tax_id=GB_VAT_KESTREL, iban=iban, bic=bic,
                 bank_name=bank_name, account_holder="Kestrel Logistics Ltd")
    hmrc_vat(p / "kestrel_vat.pdf", "KESTREL LOGISTICS LTD", GB_VAT_KESTREL, s["address"], d(-1500))
    bank_letter_iban(p / "bank_letter.pdf", bank_name, "Kestrel Logistics Ltd", iban, bic, d(-14))
    files = {"tax_certificate": "kestrel_vat.pdf", "bank_letter": "bank_letter.pdf"}
    if insurance:
        insurance_uk(p / "axa_certificate.pdf", "AXA Insurance UK plc", "Kestrel Logistics Ltd", "AXA-GL-4471209",
                     "£5,000,000", d(-200), d(19))
        files["insurance_certificate"] = "axa_certificate.pdf"
    return s, files


@scenario("kestrel_initial", "Kestrel Logistics — first attempt (incomplete)", "PENDING", "Edge 4 · Resubmission",
          "No insurance certificate and no phone number. Run this first, then one of the two resubmissions below.")
def _(p: Path):
    return _kestrel(p, phone=False, insurance=False)


@scenario("kestrel_resubmit_fixed", "Kestrel Logistics — resubmission with fixes", "APPROVED", "Edge 4 · Resubmission",
          "Supplies exactly what was asked. Previous requests are marked resolved; insurance expiring soon becomes a condition.")
def _(p: Path):
    return _kestrel(p)


@scenario("kestrel_resubmit_hijacked", "Kestrel Logistics — resubmission with new bank & gmail", "REJECTED",
          "Edge 4 · Resubmission fraud",
          "Also fixes the missing items, but silently switches bank account and the contact moves to gmail — BEC pattern.")
def _(p: Path):
    return _kestrel(p, iban=IBAN_KESTREL_NEW, email="kestrel.logistics.accounts@gmail.com", bank_name="Monzo Bank Ltd",
                    bic="MONZGB2L")


SEED_VENDORS = [
    {"id": "V-0001", "legal_name": "Orion Facility Services Ltd", "country": "GB", "tax_id": "GB3104471" + tax.gb_vat_check_digits("3104471"),
     "account_fp": "IBAN:" + IBAN_ORION, "account_masked": bank.mask(IBAN_ORION), "contact_email": "ap@orionfs.co.uk",
     "approved_at": "2026-03-02T10:00:00+00:00", "seeded": 1},
    {"id": "V-0002", "legal_name": "Pinnacle Office Products Inc", "country": "US", "tax_id": EIN_PINNACLE,
     "account_fp": f"ABA:{ABA_CHASE}:{ACCT_PINNACLE}", "account_masked": bank.mask(ACCT_PINNACLE),
     "contact_email": "billing@pinnacleoffice.com", "approved_at": "2025-11-18T09:30:00+00:00", "seeded": 1},
    {"id": "V-0003", "legal_name": "Vertex Components GmbH", "country": "DE", "tax_id": "DE29338104" + str(tax.de_vat_check_digit("29338104")),
     "account_fp": "IBAN:" + bank.iban_with_check_digits("DE", "500105175407324931"), "account_masked": "••••4931",
     "contact_email": "buchhaltung@vertex-components.de", "approved_at": "2026-06-21T14:12:00+00:00", "seeded": 1},
]


def generate() -> list[dict]:
    """(Re)build every scenario's PDFs under data/samples/<key>/ and seed the vendor master."""
    out = []
    for sc in SCENARIOS:
        folder = config.SAMPLES_DIR / sc["key"]
        folder.mkdir(parents=True, exist_ok=True)
        sub, files = sc["build"](folder)
        meta = {k: v for k, v in sc.items() if k != "build"} | {"submission": sub, "files": files}
        (folder / "scenario.json").write_text(json.dumps(meta, indent=2))
        out.append(meta)
    existing = {v["id"] for v in db.list_vendors()}
    for v in SEED_VENDORS:
        if v["id"] not in existing:
            db.add_vendor(v)
    return out


def load_all() -> list[dict]:
    return [json.loads((config.SAMPLES_DIR / sc["key"] / "scenario.json").read_text()) for sc in SCENARIOS]


if __name__ == "__main__":
    db.init()
    for m in generate():
        print(f"{m['key']:28s} expected {m['expected']}")


def to_submission(meta: dict) -> dict:
    """Scenario metadata → pipeline submission (documents point at the generated PDFs)."""
    folder = config.SAMPLES_DIR / meta["key"]
    sub = dict(meta["submission"])
    sub["documents"] = [{"slot": slot, "filename": fn, "path": str(folder / fn)} for slot, fn in meta["files"].items()]
    return sub
