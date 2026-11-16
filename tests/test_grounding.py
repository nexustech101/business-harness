"""Label/value pairing on the page, grounding flags and sources. No models."""

from __future__ import annotations

from decimal import Decimal

from core.forms import W2, Form1099NEC, form_labels
from core.layout import Block, pair_blocks, render_evidence


def _b(left, top, text, right=None):
    return Block(1, left, top, right if right is not None else left + 6 * len(text), top + 10, text)


def test_pairing_attaches_right_aligned_values_to_label_in_same_box():
    blocks = [
        _b(10, 100, "a Employee's social security number"), _b(500, 100, "4 Social security tax withheld"),
        _b(390, 125, "412-56-7890"), _b(700, 125, "4,495.00"),
    ]
    text = render_evidence(pair_blocks(blocks, form_labels(W2)))
    assert "a Employee's social security number => 412-56-7890" in text
    assert "4 Social security tax withheld => 4,495.00" in text


def test_pairing_merges_wrapped_labels_and_checkmarks():
    blocks = [
        _b(10, 100, "2 Payer made direct sales totaling $5,000 or"),
        _b(10, 111, "more of consumer products to recipient for resale"),
        _b(400, 100, "X", right=406), _b(412, 100, "FATCA filing requirement"),
    ]
    text = render_evidence(pair_blocks(blocks, form_labels(Form1099NEC) + ["FATCA filing requirement"]))
    assert "for resale => (blank)" in text
    assert "FATCA filing requirement => X" in text


def _nec_page(fed_tax="0.00"):
    """A 1099-NEC laid out like the real form: labels top-left of their boxes, values below."""
    blocks = [
        Block(1, 10, 100, 200, 110, "PAYER'S TIN"), Block(1, 30, 115, 140, 125, "27-4410983"),
        Block(1, 250, 100, 450, 110, "RECIPIENT'S TIN"), Block(1, 270, 115, 380, 125, "XXX-XX-4417"),
        Block(1, 500, 100, 700, 110, "1 Nonemployee compensation"), Block(1, 600, 115, 690, 125, "24,750.00"),
        Block(1, 750, 100, 950, 110, "4 Federal income tax withheld"),
    ]
    if fed_tax:
        blocks.append(Block(1, 880, 115, 940, 125, fed_tax))
    return pair_blocks(blocks, form_labels(Form1099NEC))


def _nec(**values):
    base = {"payer": {"name": "Acme", "tin": "27-4410983"}, "recipient": {"name": "Dev", "tin": "XXX-XX-4417"},
            "nonemployee_compensation": "24,750.00", "federal_income_tax_withheld": "0.00"}
    return Form1099NEC.model_validate({**base, **values})


def test_verify_keeps_values_under_their_own_label_and_records_where():
    from core.grounding import verify

    form = _nec()
    result = verify(form, _nec_page())
    assert result.dropped == [] and result.flags == []
    assert form.federal_income_tax_withheld == Decimal("0.00")  # a printed zero is a value
    src = result.sources["nonemployee_compensation"]
    assert (src.label, src.page, src.box) == ("1 Nonemployee compensation", 1, (600.0, 115.0, 690.0, 125.0))
    assert result.sources["recipient.tin"].label == "RECIPIENT'S TIN"


def test_verify_removes_values_not_printed_including_zero():
    from core.grounding import verify

    form = _nec(federal_income_tax_withheld="0.00")
    result = verify(form, _nec_page(fed_tax=None))  # box 4 is blank: the model's 0.00 is invented
    assert result.dropped == ["federal_income_tax_withheld"]
    assert form.federal_income_tax_withheld is None
    assert (result.flags[0].field, result.flags[0].code) == ("federal_income_tax_withheld", "not_printed")
    assert "not printed" in result.flags[0].message


def test_verify_removes_swapped_values():
    from core.grounding import verify

    form = _nec(nonemployee_compensation="0.00", federal_income_tax_withheld="24,750.00")  # boxes 1 and 4 swapped
    result = verify(form, _nec_page())
    assert set(result.dropped) == {"nonemployee_compensation", "federal_income_tax_withheld"}
    assert any(f.code == "wrong_label" and f.field == "federal_income_tax_withheld"
               and "printed under '1 Nonemployee compensation', not under its own label" in f.message for f in result.flags)


def test_verify_keeps_but_flags_a_value_whose_label_is_not_on_the_page():
    from core.grounding import verify

    page = [b for b in _nec_page() if b.text != "4 Federal income tax withheld"]
    page = pair_blocks([Block(b.page, b.left, b.top, b.right, b.bottom, b.text) for b in page], form_labels(Form1099NEC))
    form = _nec()
    result = verify(form, page)
    assert form.federal_income_tax_withheld == Decimal("0.00")
    assert [f.model_dump() for f in result.flags] == [{
        "field": "federal_income_tax_withheld", "code": "unlabeled",
        "message": "0.00 is printed in the document, but not in its labeled box; check it"}]


def test_verify_flags_never_show_a_full_tin():
    from core.grounding import verify

    form = _nec(recipient={"name": "Dev", "tin": "412-56-7890"})  # not the TIN printed on the page
    result = verify(form, _nec_page())
    assert result.dropped == ["recipient.tin"]
    assert [f.model_dump() for f in result.flags] == [{
        "field": "recipient.tin", "code": "not_printed", "message": "removed, TIN ending 7890 is not printed in the document"}]


def test_verify_checks_list_rows_under_their_column_labels():
    from core.grounding import verify

    blocks = [Block(1, 10, 100, 200, 110, "Letter code printed next to the amount"), Block(1, 300, 100, 400, 110, "Amount"),
              Block(1, 30, 115, 50, 125, "D"), Block(1, 330, 115, 390, 125, "4,087.45"),
              Block(1, 500, 100, 700, 110, "1 Wages, tips, other compensation"), Block(1, 600, 115, 690, 125, "68,412.55")]
    form = W2.model_validate({"wages_tips_other_comp": "68,412.55", "box12": [{"code": "D", "amount": "4,087.45"}]})
    result = verify(form, pair_blocks(blocks, form_labels(W2)))
    assert result.dropped == [] and result.sources["box12[0].amount"].label == "Amount"


def test_verify_takes_table_rows_from_their_printed_lines():
    from core.forms import Form1099B
    from core.grounding import verify

    line = [Block(2, 40, 120, 200, 130, "100 SH APPLE INC"), Block(2, 520, 120, 590, 130, "19,450.00")]
    form = Form1099B.model_validate({"transactions": [{"description": "100 SH APPLE INC", "proceeds": "19,450.00"}]})
    result = verify(form, [], table_lines={"transactions": [line]})
    assert result.dropped == []
    assert result.sources["transactions[0]"].box == (40.0, 120.0, 590.0, 130.0)


def test_verify_locates_text_values_without_removing_or_flagging_them():
    from core.forms import Form1095A
    from core.grounding import verify

    blocks = [Block(1, 10, 20, 400, 30, "Form W-2 Wage and Tax Statement 2025"),
              Block(1, 10, 100, 300, 110, "c Employer's name, address, and ZIP code"),
              Block(1, 20, 115, 200, 125, "Acme Industries LLC"), Block(1, 20, 130, 260, 140, "Harrisburg, PA 17101"),
              Block(1, 500, 100, 700, 110, "d Control number"), Block(1, 520, 115, 600, 125, "A-77"),
              Block(1, 10, 200, 200, 210, "Letter code printed next to the amount"), Block(1, 30, 215, 50, 225, "D"),
              Block(1, 600, 300, 800, 310, "Retirement plan"), Block(1, 600, 400, 700, 410, "PA")]
    form = W2.model_validate({"tax_year": 2025, "control_number": "A-77", "retirement_plan": True,
                              "employer": {"name": "Acme Industries LLC", "address": {"city": "Harrisburg", "state": "PA"}},
                              "employee": {"name": "Not On The Page"}, "box12": [{"code": "D"}]})
    result = verify(form, pair_blocks(blocks, form_labels(W2)))
    assert result.flags == [] and result.dropped == [] and form.employee.name == "Not On The Page"
    where = {path: (s.label, s.box[:2]) for path, s in result.sources.items()}
    assert where["employer.name"] == ("c Employer's name, address, and ZIP code", (20.0, 115.0))
    assert where["employer.address.city"][1] == (20.0, 130.0)
    assert where["employer.address.state"][1] == (20.0, 130.0)  # 2 letters: found under the party's own label
    assert where["control_number"] == ("d Control number", (520.0, 115.0))
    assert where["box12[0].code"] == ("Letter code printed next to the amount", (30.0, 215.0))
    assert where["retirement_plan"] == ("Retirement plan", (600.0, 300.0))  # a checkbox: its label
    assert where["tax_year"][1] == (10.0, 20.0)
    assert "employee.name" not in result.sources

    page = [Block(1, 10, 100, 200, 110, "6 Recipient's date of birth"), Block(1, 20, 115, 120, 125, "03/05/1990")]
    form = Form1095A.model_validate({"recipient_date_of_birth": "1990-03-05"})
    result = verify(form, pair_blocks(page, form_labels(Form1095A)))
    assert result.sources["recipient_date_of_birth"].box[:2] == (20.0, 115.0)  # printed as 03/05/1990
