"""Value parsers, form schemas and lenient validation, consistency checks, flag masking. No models."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from core.extractor import field_guide, llm_schema, validate_leniently
from core.forms import (
    FORMS,
    SSA1099,
    W2,
    BrokerTransaction,
    Form1095A,
    Form1099B,
    Form1099K,
    ScheduleK1_1065,
    form_labels,
)
from core.utils import parse_acquired, parse_bool, parse_date, parse_money, parse_month, parse_percent, parse_tin


@pytest.mark.parametrize("raw, expected", [
    ("$1,234.5", Decimal("1234.50")),
    ("(12.00)", Decimal("-12.00")),
    ("-840.00", Decimal("-840.00")),
    (68412.55, Decimal("68412.55")),
    ("3.672.21", Decimal("3672.21")), ("1.234,56", Decimal("1234.56")), ("68412.55", Decimal("68412.55")),
    ("", None), ("-", None), (None, None),
])
def test_parse_money(raw, expected):
    assert parse_money(raw) == expected


def test_parse_money_rejects_text():
    with pytest.raises(ValueError):
        parse_money("see statement")


@pytest.mark.parametrize("raw, expected", [
    ("123456789", "123-45-6789"),
    ("123-45-6789", "123-45-6789"),
    ("12-3456789", "12-3456789"),
    ("***-**-6789", "XXX-XX-6789"),
    ("xxx-xx-6789", "XXX-XX-6789"),
])
def test_parse_tin(raw, expected):
    assert parse_tin(raw) == expected


def test_parse_tin_rejects_wrong_length():
    with pytest.raises(ValueError):
        parse_tin("12345")


def test_parse_misc():
    assert parse_date("03/15/2021") == date(2021, 3, 15)
    assert parse_date("2021-03-15") == date(2021, 3, 15)
    assert parse_bool("X") is True and parse_bool("☐") is False and parse_bool(None) is None
    assert parse_percent("12.5%") == Decimal("12.5000")
    assert parse_acquired("Various") == "VARIOUS" and parse_acquired("01/15/2024") == date(2024, 1, 15)
    assert parse_month("21 January") == "January" and parse_month("Sept.") == "September"


def test_every_form_has_metadata_and_schema():
    assert len(FORMS) == 15
    for form_id, form in FORMS.items():
        assert form_id == form.FORM_ID
        assert form.TITLE and form.HINT and form.NAME in form.TITLE.replace("Schedule ", "").replace("(Form ", "(")
        schema = form.model_json_schema(mode="serialization")
        assert schema["type"] == "object"
        assert form_labels(form), form_id
        assert field_guide(form), form_id
        llm = llm_schema(form)
        assert set(llm["required"]) == set(llm["properties"])


def test_money_serialises_as_number():
    w2 = W2.model_validate({"wages_tips_other_comp": "68,412.55", "retirement_plan": "X"})
    dumped = w2.model_dump(mode="json")
    assert dumped["wages_tips_other_comp"] == 68412.55
    assert dumped["retirement_plan"] is True


def test_validate_leniently_drops_only_bad_values():
    form, flags = validate_leniently(W2, {
        "wages_tips_other_comp": "68,412.55",
        "federal_income_tax_withheld": "see attached",
        "employee": {"name": "Maria", "tin": "12"},
        "box12": [{"code": "D", "amount": "1,000.00"}],
    })
    assert form.wages_tips_other_comp == Decimal("68412.55")
    assert form.federal_income_tax_withheld is None
    assert form.employee.name == "Maria" and form.employee.tin is None
    assert form.box12[0].amount == Decimal("1000.00")
    assert sorted((f.field, f.code) for f in flags) == [("employee.tin", "unparseable"),
                                                        ("federal_income_tax_withheld", "unparseable")]


def test_consistency_checks():
    ok = W2.model_validate({"social_security_wages": "1000", "social_security_tax_withheld": "62",
                            "medicare_wages_and_tips": "1000", "medicare_tax_withheld": "14.50"})
    assert ok.consistency_checks() == []
    bad = W2.model_validate({"social_security_wages": "1000", "social_security_tax_withheld": "10"})
    (flag,) = bad.consistency_checks()
    assert (flag.field, flag.code) == ("social_security_tax_withheld", "inconsistent") and "6.2%" in flag.message
    assert SSA1099.model_validate({"benefits_paid": "100", "benefits_repaid": "0", "net_benefits": "90"}).consistency_checks()
    k1 = ScheduleK1_1065.model_validate({"capital_account": {
        "beginning_capital_account": "100", "capital_contributed": "10", "current_year_net_income": "5",
        "withdrawals_and_distributions": "15", "ending_capital_account": "100"}})
    assert k1.consistency_checks() == []


def test_new_form_consistency_checks():
    k = Form1099K.model_validate({"gross_amount": "300", "january": "100", "february": "100", "march": "50"})
    (flag,) = k.consistency_checks()
    assert flag.field == "gross_amount" and "boxes 5a-5l" in flag.message
    a = Form1095A.model_validate({"monthly": [{"month": "Jan", "enrollment_premium": "450"},
                                              {"month": "Feb", "enrollment_premium": "450"}],
                                  "annual_enrollment_premiums": "900"})
    assert a.consistency_checks() == []
    b = Form1099B.model_validate({"transactions": [{"proceeds": "100", "cost_basis": "80", "gain_or_loss": "25"}]})
    (flag,) = b.consistency_checks()
    assert flag.field == "transactions[0].gain_or_loss" and "gain or loss" in flag.message


def test_broker_section_headings():
    s = BrokerTransaction.section
    assert s("Short-term transactions for which basis is reported to the IRS (Box A)") == \
        {"term": "short", "basis_reported_to_irs": True, "form_8949_box": "A"}
    assert s("LONG TERM - NONCOVERED") == {"term": "long", "basis_reported_to_irs": False, "form_8949_box": "E"}
    assert s("100 SH APPLE INC") is None


def test_flag_messages_never_carry_a_full_ssn():
    from core.flags import Flag

    flag = Flag(field="employee.tin", code="multiple_values", message="kept '412-56-7890', also saw 412 56 7891")
    assert flag.message == "kept 'XXX-XX-7890', also saw XXX-XX-7891"
