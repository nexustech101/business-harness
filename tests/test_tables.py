"""Table rows (1099-B transactions, 1095-A months) read from page blocks. No models."""

from __future__ import annotations

from decimal import Decimal

from core.forms import BrokerTransaction, MonthlyCoverage
from core.layout import Block
from core.tables import read_table


def _row(top, cells, page=1):
    return [Block(page, left, top, left + 8 * len(text), top + 10, text) for left, text in cells]


HEADER_1099B = [(40, "Description of property"), (300, "Date acquired"), (400, "Date sold or disposed"),
                (520, "Proceeds"), (620, "Cost or other basis"), (740, "Wash sale loss disallowed"),
                (880, "Gain or loss")]


def test_table_reads_1099b_rows_sections_and_wrapped_descriptions():
    blocks = (
        _row(80, [(40, "SHORT-TERM TRANSACTIONS FOR COVERED TAX LOTS - Form 8949 with Box A checked")])
        + _row(100, HEADER_1099B)
        + _row(110, [(40, "40 SH VANGUARD TOTAL STK"), (300, "06/19/2025"), (400, "09/04/2025"), (520, "9,959.91"),
                     (620, "7,212.40"), (880, "2,747.51")])
        + _row(120, [(40, "100 SH APPLE INC"), (300, "01/15/2025"), (400, "06/02/2025"), (520, "19,450.00"),
                     (620, "17,210.00"), (880, "2,240.00")])
        + _row(131, [(40, "CUSIP 037833100")])
        + _row(150, [(40, "Total Short-term"), (520, "19,450.00"), (620, "17,210.00")])
        + _row(200, [(40, "LONG-TERM TRANSACTIONS FOR NONCOVERED TAX LOTS - Box E")])
        + _row(30, HEADER_1099B, page=2)
        + _row(50, [(40, "50 SH TOTALENERGIES SE"), (300, "VARIOUS"), (400, "11/03/2025"), (520, "2,900.00"),
                    (620, "3,400.00"), (740, "120.00"), (880, "-380.00")], page=2)
    )
    table = read_table(blocks, BrokerTransaction)
    rows = [BrokerTransaction.model_validate(r) for r in table.rows]
    assert len(rows) == 3  # the Total line is not a sale; a fund named "... TOTAL ..." is
    v, a, e = rows
    assert v.description == "40 SH VANGUARD TOTAL STK"
    assert a.description == "100 SH APPLE INC CUSIP 037833100"
    assert (a.term, a.basis_reported_to_irs, a.form_8949_box) == ("short", True, "A")
    assert a.proceeds == Decimal("19450.00") and a.gain_or_loss == Decimal("2240.00")
    assert e.description.startswith("50 SH TOTALENERGIES")  # 'Total' inside a name is not a total line
    assert (e.term, e.basis_reported_to_irs, e.form_8949_box) == ("long", False, "E")
    assert e.date_acquired == "VARIOUS" and e.wash_sale_loss_disallowed == Decimal("120.00")


def test_table_unlabeled_month_column_and_annual_totals():
    blocks = (
        # Long headers wrap inside their columns; only the first line is needed.
        [Block(1, 300, 100, 460, 110, "A. Monthly enrollment premiums"),
         Block(1, 500, 100, 690, 110, "B. Monthly second lowest cost silver plan"),
         Block(1, 720, 100, 920, 110, "C. Monthly advance payment of premium tax credit")]
        + _row(120, [(40, "21 January"), (330, "450.00"), (530, "520.00"), (760, "300.00")])
        + _row(136, [(40, "22 February"), (330, "450.00"), (530, "520.00"), (760, "300.00")])
        + _row(152, [(40, "33 Annual Totals"), (330, "900.00"), (530, "1,040.00"), (760, "600.00")])
    )
    rows = [MonthlyCoverage.model_validate(r) for r in read_table(blocks, MonthlyCoverage).rows]
    assert [r.month for r in rows] == ["January", "February"]
    assert rows[1].advance_ptc == Decimal("300.00")


def test_table_without_header_reads_nothing():
    assert read_table(_row(100, [(40, "Proceeds"), (300, "1,000.00")]), BrokerTransaction).rows == []
