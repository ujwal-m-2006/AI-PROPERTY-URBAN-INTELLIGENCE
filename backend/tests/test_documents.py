"""Module 27 guarantees — document intelligence.

This module handles the only genuinely sensitive input the platform accepts: a
real person's property document. Three properties matter more than whether
extraction works well.

  1. Nothing is stored.
  2. Personal data is never echoed back.
  3. A consistent document is never reported as a verified one.

Extraction quality is a convenience. Those three are the reason the module is
safe to ship.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.services import documents

client = TestClient(app)

# Deliberately contains a ward number that does NOT match the location below,
# plus personal data, so the negative paths are exercised rather than assumed.
KHATA = """KHATA CERTIFICATE
Bruhat Bengaluru Mahanagara Palike
Khata No: 123/456/78
PID No: 15-25-123
Owner: Ramesh Kumar
Ward No: 111
Survey No: 36
Taluk: Bangalore East
Hobli: Varthur
Village: Marathhalli
Extent: 2400 sq ft
Mobile: 9876543210
Aadhaar: 1234 5678 9012
"""

# Marathahalli — inside the revenue sheets, ward 44.
POINT = {"lat": 12.9591, "lng": 77.6974}


def analyse(text: str = KHATA, **extra) -> dict:
    body = {"text": text, "city": "bengaluru", **POINT, **extra}
    r = client.post("/api/v1/documents/analyze", json=body)
    assert r.status_code == 200, r.text
    return r.json()


# --- the three that matter ----------------------------------------------


def test_nothing_is_stored() -> None:
    d = analyse()
    assert d["retention"]["stored"] is False
    assert "discarded" in d["retention"]["note"]


def test_personal_data_is_detected_but_never_echoed_back() -> None:
    d = analyse()
    blob = str(d)

    assert d["personal_data"]["present"] is True
    assert "owner_name" in d["personal_data"]["kinds_detected"]

    # The values themselves must not appear anywhere in the response.
    assert "Ramesh" not in blob
    assert "9876543210" not in blob
    assert "1234 5678 9012" not in blob


def test_a_consistent_document_is_never_reported_as_verified() -> None:
    """The single most dangerous thing this module could claim."""
    d = analyse()
    assert d["summary"]["verified"] is False
    why = d["summary"]["why_never_verified"]
    assert "NOT verification" in why
    assert "Khata is not title" in why


# --- cross-checking ------------------------------------------------------


def test_mismatched_ward_is_flagged_inconsistent() -> None:
    d = analyse()
    ward = next(c for c in d["cross_check"] if c["field"] == "Ward number")
    assert ward["verdict"] == documents.MISMATCH
    assert ward["document"] == "111"
    assert str(ward["platform"]) == "44"
    # An inconsistency is a prompt to check, not an accusation.
    assert "not a finding of fraud" in ward["note"]


def test_matching_revenue_fields_are_consistent() -> None:
    d = analyse()
    verdicts = {c["field"]: c["verdict"] for c in d["cross_check"]}
    for field in ("Taluk", "Hobli", "Village"):
        assert verdicts[field] == documents.MATCH, f"{field} did not match"


def test_missing_field_is_not_found_rather_than_absent() -> None:
    d = analyse("Khata No: 99/1\nTaluk: Bangalore East\n")
    ward = next(c for c in d["cross_check"] if c["field"] == "Ward number")
    assert ward["verdict"] == documents.NOT_FOUND
    assert "not evidence it is absent" in ward["note"]


def test_without_a_location_nothing_is_cross_checked() -> None:
    r = client.post("/api/v1/documents/analyze",
                    json={"text": KHATA, "city": "bengaluru"})
    d = r.json()
    assert r.status_code == 200
    assert "No location was supplied" in d["cross_check_note"]
    assert all(c["verdict"] in (documents.UNVERIFIABLE, documents.NOT_FOUND)
               for c in d["cross_check"])


# --- refusing what it cannot read ---------------------------------------


def test_image_upload_is_refused_rather_than_guessed() -> None:
    """No OCR engine is installed. Returning fields would be fabrication."""
    r = client.post("/api/v1/documents/upload",
                    files={"file": ("khata.jpg", b"\xff\xd8\xff\xe0fake", "image/jpeg")})
    d = r.json()
    assert r.status_code == 200
    assert d["analysed"] is False
    assert d["ocr_status"] == "NOT INSTALLED"
    assert "fabrication" in d["reason"]
    assert d["stored"] is False


def test_text_upload_is_analysed() -> None:
    r = client.post("/api/v1/documents/upload",
                    files={"file": ("khata.txt", KHATA.encode(), "text/plain")})
    d = r.json()
    assert d["analysed"] is True
    assert d["fields_found"] >= 5
    assert "Ramesh" not in str(d)


def test_capabilities_states_what_it_cannot_do() -> None:
    d = client.get("/api/v1/documents/capabilities").json()
    cannot = " ".join(d["cannot_do"]).lower()
    assert "verify" in cannot
    assert "title" in cannot
    assert d["retention"]["stored"] is False
    assert d["privacy"]["personal_data_echoed"] is False
    # It must point somewhere that CAN verify.
    assert d["official_sources"]
    assert all(s["url"].startswith("https://") for s in d["official_sources"])


def test_extraction_is_labelled_indicative() -> None:
    d = analyse()
    assert "INDICATIVE" in d["extraction_method"]
    assert "INDICATIVE" in d["document_type"]["method"]
