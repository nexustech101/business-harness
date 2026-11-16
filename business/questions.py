"""business/questions.py

The interview's question bank and how the next questions are chosen.

The bank follows from what every business has, whatever its size: an identity and an offering, customers,
a way of making money, operations that deliver, departments and the roles in them (who does what, who reports
to whom), books and reports, sales and marketing, tools (which drive connector recommendations), records and
where they live, information passed between departments, obligations, and goals. Each question says which
profile fields its answer informs (`fills`); required questions make the interview complete.

`interview_state(answers, profile)` is pure: a question is done when it was answered or every field it fills
is already in the profile (the owner edited it, or the partner learned it from a document). The next questions
are the open ones, required first, then those of the least covered areas, in bank order.

*Usage:*
>>> state = interview_state({"identity.name": answer}, profile)
>>> [q.id for q in state.next]
['identity.what', 'offering.list', ...]
"""

from __future__ import annotations

from collections.abc import Mapping

from business.schema import Area, AreaProgress, BusinessProfile, InterviewState, Question

NEXT = 5  # questions offered at a time

AREA_LABELS: dict[str, str] = {
    "identity": "Identity", "offering": "Products and services", "customers": "Customers and market",
    "revenue": "Revenue and pricing", "operations": "Operations and delivery", "departments": "Departments",
    "roles": "Roles and responsibilities", "finance": "Finance and accounting",
    "sales_marketing": "Sales and marketing", "tools": "Tools and systems", "data": "Data and documents",
    "information_flow": "Information flow", "compliance": "Compliance", "goals": "Goals and pain points",
}

# (id, text, purpose, fills, required); the area is the id's prefix.
BANK: list[tuple[str, str, str, list[str], bool]] = [
    ("identity.name", "What is the business called?", "Names the workspace and every assistant's context.",
     ["name"], True),
    ("identity.what", "In a few sentences, what does the business do?",
     "The summary every assistant starts from.", ["summary"], True),
    ("identity.industry", "Which industry or trade is it in?", "Sets the vocabulary and the usual obligations.",
     ["industry"], False),
    ("identity.size", "How many people work in it, and is it solo, growing or established?",
     "Scales the structure the partner proposes.", ["team_size", "stage"], True),
    ("identity.locations", "Where does it operate: locations, regions, online only?",
     "Location drives taxes, licenses and delivery.", ["locations"], False),
    ("offering.list", "What do you sell? List the main products or services.",
     "Assistants refer to the offering by name.", ["offerings"], True),
    ("offering.delivery", "How is each product or service delivered to the customer?",
     "Maps the operations an assistant could take over.", ["offerings"], False),
    ("customers.who", "Who are your customers, and how do they find you?",
     "Shapes the sales and marketing assistants.", ["customers"], True),
    ("customers.channels", "Through which channels do customers buy or contact you (store, website, phone, "
     "marketplace, email)?", "Names the systems orders and messages come from.", ["customers", "tools"], False),
    ("revenue.model", "How does the business make money: one-off sales, subscriptions, retainers, fees?",
     "The revenue model sets what finance tracks.", ["business_model", "financials.revenue_streams"], True),
    ("revenue.pricing", "How do you set prices, and how do customers pay?",
     "Pricing and payment methods for invoicing and payment connectors.", ["financials.pricing"], False),
    ("revenue.costs", "What are the main costs?", "Cost centers for bookkeeping and reports.",
     ["financials.cost_centers"], False),
    ("operations.steps", "Walk me through what happens from a new order or client to done.",
     "The core process; each step is a candidate for automation.", ["flows"], True),
    ("operations.bottlenecks", "Which steps take the most time or go wrong most often?",
     "Where an assistant saves the most.", ["pain_points"], False),
    ("operations.suppliers", "Who do you depend on: suppliers, contractors, partners?",
     "Outside parties assistants may need to contact or track.", [], False),
    ("departments.list", "Which departments or areas of work does the business have (even if one person "
     "covers several)?", "Each department can get its own assistant and knowledge scope.", ["departments"], True),
    ("departments.purpose", "What is each department responsible for, and who leads it?",
     "Sets each department's purpose, head and responsibilities.",
     ["departments.purpose", "departments.head", "departments.responsibilities"], False),
    ("roles.list", "Which roles exist, and who holds each one?",
     "Roles become assistants; people tell who to hand off to.", ["roles", "roles.people"], True),
    ("roles.duties", "For each role: what are its recurring duties (daily, weekly, monthly)?",
     "Duties become an assistant's instructions.", ["roles.duties"], True),
    ("roles.reporting", "Who reports to whom?", "The chain an assistant escalates through.",
     ["roles.reports_to"], False),
    ("roles.tools", "Which tools does each role use?", "Which connectors each assistant needs.",
     ["roles.tools"], False),
    ("finance.method", "Do you keep the books on a cash or an accrual basis?",
     "Sets how the accountant assistant records income and expenses.", ["financials.accounting_method"], True),
    ("finance.year", "When does your fiscal year end?", "Month-end and year-end deadlines.",
     ["financials.fiscal_year_end"], False),
    ("finance.reports", "Which financial reports do you produce or need (P&L, cash flow, sales tax returns...)?"
     " How often?", "Reports an assistant can prepare.", ["financials.reporting"], True),
    ("finance.who", "Who keeps the books and who does the taxes: in-house, a bookkeeper, an accountant?",
     "Hand-offs between the finance assistant and people.", ["roles"], False),
    ("sales_marketing.process", "How do you win a sale, from first contact to paid?",
     "The sales pipeline an assistant can follow up on.", ["flows"], True),
    ("sales_marketing.channels", "Where do you market: social media, email, ads, referrals, events?",
     "Channels for a marketing or social media assistant.", ["tools", "customers"], False),
    ("tools.list", "Which software do you use, and for what (accounting, email, calendar, CRM, store, files, "
     "chat, payments)?", "Each tool can become a connector the assistants act through.", ["tools"], True),
    ("tools.pain", "Which tools do you dislike or work around with spreadsheets or copy-paste?",
     "Manual hand-offs between tools are automation candidates.", ["pain_points"], False),
    ("data.where", "Where do your records live: invoices, contracts, customer lists, price lists, SOPs?",
     "Where assistants find documents, and what to upload.", ["tools"], True),
    ("data.documents", "Which documents would you like the assistants to know (upload them here)?",
     "Documents become searchable knowledge per department.", [], False),
    ("information_flow.reports", "Which reports or updates go from one part of the business to another, and how "
     "often?", "Recurring hand-offs assistants can prepare and post.", ["flows"], True),
    ("information_flow.handoffs", "When work passes from one person or department to the next, how is it handed "
     "over (email, chat, a shared sheet, a tool)?", "The channels shared notes and connectors replace.", ["flows"],
     False),
    ("information_flow.shared", "Which records are shared between departments (customer list, orders, "
     "inventory)?", "Shared records decide which assistants share notes topics.", ["flows"], False),
    ("compliance.duties", "Which licenses, regulations or filings apply (sales tax, payroll, industry rules)?",
     "Deadlines and rules assistants must respect.", ["compliance"], True),
    ("goals.next", "What do you want to achieve in the next 12 months?", "What the partner optimizes for.",
     ["goals"], True),
    ("goals.pain", "What takes your time that you would hand off first?", "The first assistant to build.",
     ["pain_points"], True),
]

QUESTIONS: dict[str, Question] = {
    qid: Question(id=qid, area=qid.split(".")[0], text=text, purpose=purpose, fills=fills)
    for qid, text, purpose, fills, _ in BANK
}
REQUIRED: frozenset[str] = frozenset(qid for qid, *_, required in BANK if required)


def _filled(value) -> bool:
    if isinstance(value, list):
        return any(_filled(v) for v in value)
    return value not in (None, "", {}, [])


def covered(profile: BusinessProfile, path: str) -> bool:
    """`path` names a field (`summary`), a nested one (`financials.pricing`) or a field of list items
    (`roles.duties`: some role has duties)."""
    head, _, rest = path.partition(".")
    value = getattr(profile, head)
    if not rest:
        return _filled(value)
    if isinstance(value, list):
        return any(_filled(getattr(item, rest)) for item in value)
    return _filled(getattr(value, rest))


def done(question: Question, answered: Mapping[str, object], profile: BusinessProfile) -> bool:
    if question.id in answered:
        return True
    return bool(question.fills) and all(covered(profile, f) for f in question.fills)


def interview_state(answered: Mapping[str, object], profile: BusinessProfile) -> InterviewState:
    """`answered`: question id -> answer (only the keys matter)."""
    finished = {q.id for q in QUESTIONS.values() if done(q, answered, profile)}
    areas: list[AreaProgress] = []
    for area, label in AREA_LABELS.items():
        ids = [q.id for q in QUESTIONS.values() if q.area == area]
        areas.append(AreaProgress(area=area, label=label, answered=sum(i in finished for i in ids), total=len(ids)))
    coverage: dict[Area, float] = {a.area: a.answered / a.total for a in areas}
    order = {qid: i for i, qid in enumerate(QUESTIONS)}
    open_ = sorted((q for q in QUESTIONS.values() if q.id not in finished),
                   key=lambda q: (q.id not in REQUIRED, coverage[q.area], order[q.id]))
    return InterviewState(answered=len(finished), total=len(QUESTIONS), complete=finished >= REQUIRED,
                          areas=areas, next=open_[:NEXT])
