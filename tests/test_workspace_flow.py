"""The workspace end to end with the real `ConnectorHub` (no fake hub): a connector on an in-process MCP server,
an assistant using it, the write policy queueing a call, and the approval running it. Hub and workspace share
one database file, as in production."""

from __future__ import annotations

from business.runner import exposed_name
from business.schema import ApprovalDecision, AssistantSpec, ChatMessage, RunRequest, WritePolicy
from business.service import Business
from tests.fakes import Chat, business_config, openai_answer, openai_turn
from tests.test_connectors import Provider, by_hand, make_hub, run


def test_assistant_reads_freely_and_a_write_waits_for_approval_on_a_real_connector(tmp_path):
    import agent
    from tests.fakes import Embeddings, config

    provider = Provider(tokens={"secret-token"})
    hub = make_hub(tmp_path, provider)
    chat = Chat([])
    library, assistant = agent.build(config(tmp_path), chat, Embeddings())
    business = Business(business_config(tmp_path), library, assistant.chat, hub)
    assert business.config.database == hub.path  # one file for both

    async def scenario():
        crm = await hub.add("1", by_hand(auth="bearer", token="secret-token"), admin=False)
        assert (crm.status, crm.tool_count) == ("connected", 2)
        spec = AssistantSpec(name="Billing", role="Charges customers", connectors=[crm.id],
                             policy=WritePolicy(default="ask"))
        billing = business.create_assistant("1", spec)
        business.set_status("1", billing.id, "active")
        context = await business.context("1", billing.id)
        assert {f"{crm.id}/lookup", f"{crm.id}/charge"} <= set(context.tools)
        lookup, charge = (exposed_name(crm.id, tool, set()) for tool in ("lookup", "charge"))  # as the model sees them
        chat.__init__([openai_turn("Looking up Rosa, then charging her.", (lookup, {"customer": "Rosa"}),
                                   (charge, {"amount": 40})),
                       openai_answer("Charge queued for your approval.")])

        result = await business.run("1", billing.id, RunRequest(messages=[ChatMessage(role="user", content="Bill Rosa")]))
        runs = {r.tool: r for r in result.tool_runs}
        assert (runs["lookup"].outcome, runs["lookup"].result) == ("ran", "found Rosa")  # read: runs
        assert runs["charge"].outcome == "pending_approval"  # write under `ask`: queued, not run
        (pending,) = business.approvals("1", "pending")
        assert (pending.tool, pending.arguments, pending.reason) == ("charge", {"amount": 40},
                                                                     "Looking up Rosa, then charging her.")
        assert business.approvals("2", None) == []  # another key's workspace

        done = await business.decide("1", pending.id, ApprovalDecision(approve=True), "owner")
        assert (done.status, done.result) == ("executed", "charged 40")
        return provider.seen_auth

    seen = run(provider, scenario)
    assert seen and all(a == "Bearer secret-token" for a in seen)
