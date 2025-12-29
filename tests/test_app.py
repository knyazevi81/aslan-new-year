from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import create_app

client = TestClient(create_app())


def _base_answers():
    # Minimal required answers to get a quote
    return {
        "FLD_OBJECTS_SELECTED": ["OBJ_SANTA"],
        "FLD_INSURED_SUM": 500000,
        "FLD_DEDUCTIBLE": 0,
        "FLD_COVERAGE_LIMIT": 500000,
        "FLD_POLICYHOLDER_NAME": "Иван Иванов",
        "FLD_POLICYHOLDER_PHONE": "+79990000000",
        "FLD_POLICYHOLDER_EMAIL": "demo@example.test",
        "FLD_PAYMENT_METHOD": "PAY_CARD",
        # risks empty by default
        "FLD_RISKS_SLED": [],
        "FLD_RISKS_REINDEER": [],
        "FLD_RISKS_BAG": [],
        "FLD_RISKS_ELVES": [],
        "FLD_RISKS_PROD_BREAK": [],
        "FLD_RISKS_TPL": [],
        "FLD_RISKS_FORCE_MAJEURE": [],
    }


def test_validation_unknown_dictionary_option_400():
    ans = _base_answers()
    ans["FLD_OBJECTS_SELECTED"] = ["OBJ_NOPE"]
    r = client.post("/api/quote", json={"answers": ans})
    assert r.status_code == 400
    body = r.json()
    assert "fieldErrors" in body
    assert "FLD_OBJECTS_SELECTED" in body["fieldErrors"]


def test_pdf_smoke_starts_with_percent_pdf():
    ans = _base_answers()
    r = client.post("/api/policy/pdf", json={"answers": ans})
    assert r.status_code == 200
    assert r.content[:4] == b"%PDF"


def test_monotonicity_add_risk_does_not_decrease_premium():
    # choose two risks with weight 1 (from schema)
    risk1 = "R_SLED_HARD_LANDING_BREAK"
    risk2 = "R_FM_CAT_ATTACK"

    ans1 = _base_answers()
    ans1["FLD_RISKS_SLED"] = [risk1]

    r1 = client.post("/api/quote", json={"answers": ans1})
    assert r1.status_code == 200
    p1 = r1.json()["premium_total"]

    ans2 = _base_answers()
    ans2["FLD_RISKS_SLED"] = [risk1, risk2]  # more risks => higher/equal premium
    r2 = client.post("/api/quote", json={"answers": ans2})
    assert r2.status_code == 200
    p2 = r2.json()["premium_total"]

    assert p2 >= p1
