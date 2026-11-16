"""business/catalog.py

The connector store: built-in apps (`builtin=True`: they run inside this app, e.g. the workspace database of
business/database.py) and official MCP servers of well-known business tools, as their publishers document
them (sources in docs/CONNECTORS.md). `url` is None when the server address depends on the customer's account,
workspace or instance; the description then says where the owner finds it. `tagline` is the one line a store
card shows; `description` is the setup text of the add dialog; `also_in` lists further categories.

`auth` is how this app signs in: `oauth` (the MCP authorization flow, see business/mcp_client.py), `bearer` (a token
or API key sent as `Authorization: Bearer`), or `none`.

    from business.catalog import LISTINGS, listing
    listing("stripe").url  # "https://mcp.stripe.com"
"""

from __future__ import annotations

from business.schema import ConnectorListing

_NO_DCR = ("The provider has no dynamic client registration: create an OAuth client with it, register "
           "<public_url>/v1/connectors/oauth/callback as its redirect URL, and enter the client as the token in "
           "the form `client_id:client_secret`.")

_GOOGLE_DOCS = "https://developers.google.com/workspace/guides/configure-mcp-servers"
_GOOGLE_PREVIEW = ("Requires membership in the Google Workspace Developer Preview Program and an OAuth client in "
                   "your Google Cloud project. ")

LISTINGS: list[ConnectorListing] = [
    ConnectorListing(
        id="workspace-database", name="Workspace database", publisher="Built in", category="Data",
        tagline="Your own database: tables you and your assistants build, fill and query.",
        description="A private SQLite database stored with this workspace. Create tables for anything you track "
                    "(customers, orders, inventory, leads), import spreadsheets as CSV, and manage rows on the "
                    "Databases page. Assistants read it freely; their writes follow each assistant's policy. Add "
                    "it more than once to keep separate databases.",
        capabilities=["Create tables", "Insert, update and delete rows", "SQL queries", "CSV import and export"],
        availability="Runs locally", docs_url="", transport="builtin", url=None, auth="none",
        builtin=True),
    ConnectorListing(
        id="google-drive", name="Google Drive", publisher="Google", category="Storage",
        tagline="Find, read and file documents in Drive.",
        description="Google's remote Drive server. " + _GOOGLE_PREVIEW + _NO_DCR,
        capabilities=["Search files", "Read file contents", "Create and organize files", "Shared drives"],
        availability="Official, Developer Preview", docs_url=_GOOGLE_DOCS,
        transport="streamable_http", url="https://drivemcp.googleapis.com/mcp/v1", auth="oauth", featured=True),
    ConnectorListing(
        id="google-docs", name="Google Docs", publisher="Google", category="Storage",
        also_in=["Productivity"],
        tagline="Read, draft and edit documents in Google Docs.",
        description="Google's remote Docs server. " + _GOOGLE_PREVIEW + _NO_DCR,
        capabilities=["Read documents", "Create documents", "Edit text"],
        availability="Official, Developer Preview", docs_url=_GOOGLE_DOCS,
        transport="streamable_http", url="https://docsmcp.googleapis.com/mcp/v1", auth="oauth", featured=True),
    ConnectorListing(
        id="google-sheets", name="Google Sheets", publisher="Google", category="Productivity",
        also_in=["Storage", "Data"],
        tagline="Read and update spreadsheets.",
        description="Google's remote Sheets server. " + _GOOGLE_PREVIEW + _NO_DCR,
        capabilities=["Read ranges", "Write cells", "Create spreadsheets"],
        availability="Official, Developer Preview", docs_url=_GOOGLE_DOCS,
        transport="streamable_http", url="https://sheetsmcp.googleapis.com/mcp/v1", auth="oauth"),
    ConnectorListing(
        id="gmail", name="Gmail", publisher="Google", category="Communication",
        tagline="Search, read and draft email.",
        description="Google's remote Gmail server. " + _GOOGLE_PREVIEW + _NO_DCR,
        capabilities=["Search mail", "Read threads", "Draft and send"],
        availability="Official, Developer Preview", docs_url=_GOOGLE_DOCS,
        transport="streamable_http", url="https://gmailmcp.googleapis.com/mcp/v1", auth="oauth"),
    ConnectorListing(
        id="google-calendar", name="Google Calendar", publisher="Google", category="Productivity",
        tagline="Check availability and manage events.",
        description="Google's remote Calendar server. " + _GOOGLE_PREVIEW + _NO_DCR,
        capabilities=["List events", "Create and update events", "Find free time"],
        availability="Official, Developer Preview", docs_url=_GOOGLE_DOCS,
        transport="streamable_http", url="https://calendarmcp.googleapis.com/mcp/v1", auth="oauth"),
    ConnectorListing(
        id="google-workspace", name="Google Workspace (other products)", publisher="Google",
        category="Productivity",
        tagline="Slides, Chat, Contacts and Classroom: one connector per product.",
        description="One remote server per product, at https://<product>mcp.googleapis.com/mcp/v1 (Slides "
                    "slidesmcp, Chat chatmcp, Classroom classroommcp; Contacts https://people.googleapis.com/mcp/v1; "
                    "all URLs in the docs): add one connector per product with its URL. " + _GOOGLE_PREVIEW + _NO_DCR,
        capabilities=["Slides", "Chat", "Contacts", "Classroom"],
        availability="Official, Developer Preview", docs_url=_GOOGLE_DOCS,
        transport="streamable_http", url=None, auth="oauth"),
    ConnectorListing(
        id="dropbox", name="Dropbox", publisher="Dropbox", category="Storage",
        tagline="Search, read and organize files in Dropbox.",
        description="Dropbox's remote server; sign in with your Dropbox account. If the sign-in reports that "
                    "Dropbox offers no client registration, create an app in the Dropbox App Console, register "
                    "<public_url>/v1/connectors/oauth/callback as its redirect URL, and enter it as the token in "
                    "the form `client_id:client_secret`.",
        capabilities=["Search files", "Read file contents", "Upload and organize files", "Shared links"],
        availability="Official remote server, open beta",
        docs_url="https://help.dropbox.com/integrations/connect-dropbox-mcp-server",
        transport="streamable_http", url="https://mcp.dropbox.com/mcp", auth="oauth", featured=True),
    ConnectorListing(
        id="box", name="Box", publisher="Box", category="Storage",
        tagline="Search, read and manage content in Box.",
        description="Box's hosted server. A Box admin enables it under Admin Console > Integrations > Box MCP "
                    "Server, where the OAuth client ID and secret are shown. " + _NO_DCR,
        capabilities=["Search content", "Read files", "Folders and collaboration", "Box AI"],
        availability="Official hosted server", docs_url="https://developer.box.com/guides/box-mcp/remote",
        transport="streamable_http", url="https://mcp.box.com", auth="oauth"),
    ConnectorListing(
        id="google-ads", name="Google Ads", publisher="Google", category="Marketing",
        tagline="Read campaign performance, budgets and account structure.",
        description="Google's server runs locally (stdio, admin keys: `pipx run --spec "
                    "git+https://github.com/googleads/google-ads-mcp.git google-ads-mcp`) or as your own Cloud Run "
                    "deployment; add the deployment's URL (ending in /mcp). It enforces Google OAuth 2.0. " + _NO_DCR,
        capabilities=["List accessible accounts", "GAQL search: campaign performance, budgets, status",
                      "Resource metadata"],
        availability="Official, read-only",
        docs_url="https://developers.google.com/google-ads/api/docs/developer-toolkit/mcp-server",
        transport="streamable_http", url=None, auth="oauth"),
    ConnectorListing(
        id="microsoft-365", name="Microsoft 365 (Work IQ)", publisher="Microsoft", category="Productivity",
        also_in=["Storage", "Communication"],
        tagline="Work across Outlook, Teams, OneDrive and SharePoint.",
        description="Work IQ MCP: one endpoint whose generic tools reach Microsoft 365 data (mail, calendar, Teams "
                    "chats, search). Sign-in with Microsoft Entra ID; the tenant must be enabled for Work IQ.",
        capabilities=["Outlook mail and calendar", "Teams", "SharePoint", "OneDrive", "Word", "Search"],
        availability="Official; some offerings in preview",
        docs_url="https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/work-iq/mcp/overview",
        transport="streamable_http", url="https://workiq.svc.cloud.microsoft/mcp", auth="oauth", featured=True),
    ConnectorListing(
        id="hubspot", name="HubSpot", publisher="HubSpot", category="CRM",
        tagline="Read and update contacts, companies, deals and tickets.",
        description="Remote HubSpot server. Create the MCP connector app in HubSpot (its details page gives the "
                    "client ID, secret and redirect URL; PKCE required). " + _NO_DCR,
        capabilities=["CRM objects read/write: contacts, companies, deals, tickets, products, invoices, quotes",
                      "Engagements: calls, emails, meetings, notes, tasks", "Read-only: owners, teams, campaigns, "
                      "pages, blog posts"],
        availability="Official remote server",
        docs_url="https://developers.hubspot.com/docs/apps/developer-platform/build-apps/"
                 "integrate-with-the-remote-hubspot-mcp-server",
        transport="streamable_http", url="https://mcp.hubspot.com", auth="oauth", featured=True),
    ConnectorListing(
        id="salesforce", name="Salesforce", publisher="Salesforce", category="CRM",
        tagline="Work with the records and APIs of your Salesforce org.",
        description="Hosted MCP servers configured by an admin in your Salesforce org; the server URL comes from "
                    "that configuration (see docs). OAuth 2.0 with PKCE through an External Client App, whose "
                    "consumer key is the client ID. " + _NO_DCR + " Billed through Flex Credits.",
        capabilities=["Records (sObjects)", "Salesforce APIs", "Per-user permissions"],
        availability="Official hosted servers",
        docs_url="https://developer.salesforce.com/docs/platform/hosted-mcp-servers/guide/"
                 "client-connection-overview.html",
        transport="streamable_http", url=None, auth="oauth"),
    ConnectorListing(
        id="gohighlevel", name="HighLevel (LeadConnector)", publisher="HighLevel", category="CRM",
        tagline="Manage contacts, conversations, opportunities and calendars.",
        description="LeadConnector server: four unified tools over 550+ operations; you choose the sub-accounts "
                    "during OAuth consent. HighLevel documents one URL per client; this is the OpenAI-compatible "
                    "one (others: /mcp/anthropic/v2, /mcp/cursor/v2).",
        capabilities=["Contacts", "Conversations", "Opportunities", "Calendars", "Payments", "Workflows"],
        availability="Official LeadConnector server",
        docs_url="https://marketplace.gohighlevel.com/docs/other/mcp",
        transport="streamable_http", url="https://services.leadconnectorhq.com/mcp/openai/v2/", auth="oauth"),
    ConnectorListing(
        id="snowflake", name="Snowflake", publisher="Snowflake", category="Data",
        tagline="Query governed data with Cortex Analyst, Search and SQL.",
        description="Snowflake-managed server per MCP server object: "
                    "https://<account_url>/api/v2/databases/{database}/schemas/{schema}/mcp-servers/{name}. Snowflake "
                    "OAuth (security integration). " + _NO_DCR,
        capabilities=["Cortex Analyst", "Cortex Search", "SQL", "Tools only"],
        availability="Official managed server",
        docs_url="https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-agents-mcp",
        transport="streamable_http", url=None, auth="oauth"),
    ConnectorListing(
        id="stripe", name="Stripe", publisher="Stripe", category="Payments",
        tagline="Look up customers, payments, invoices and subscriptions.",
        description="Stripe's remote server. OAuth (pick live or sandbox accounts at consent), or add it with "
                    "auth 'bearer' and an agent API key. Some writes need human confirmation in the Dashboard.",
        capabilities=["Read and write the Stripe API (customers, payments, invoices, subscriptions, refunds...)",
                      "Analytics (preview)", "Documentation search"],
        availability="Official remote server",
        docs_url="https://docs.stripe.com/mcp",
        transport="streamable_http", url="https://mcp.stripe.com", auth="oauth", featured=True),
    ConnectorListing(
        id="square", name="Square", publisher="Square", category="Payments",
        tagline="Work with customers, orders and catalog items.",
        description="Remote server with OAuth login (production resources only); Square keeps an allowlist of MCP "
                    "clients, so a client may need approval before it can connect.",
        capabilities=["Customers", "Orders", "Catalog items", "Square API"],
        availability="Official, beta",
        docs_url="https://developer.squareup.com/docs/mcp",
        transport="streamable_http", url="https://mcp.squareup.com/mcp", auth="oauth"),
    ConnectorListing(
        id="slack", name="Slack", publisher="Slack", category="Communication",
        tagline="Search, read and send messages; work with canvases and lists.",
        description="Slack's server (no SSE). Needs a registered Slack app (directory-published or internal) using "
                    "confidential OAuth with user-token scopes. " + _NO_DCR,
        capabilities=["Search messages, files, users, channels", "Send, schedule and draft messages",
                      "Read channels and threads", "Canvases", "Lists"],
        availability="Official server",
        docs_url="https://docs.slack.dev/ai/slack-mcp-server",
        transport="streamable_http", url="https://mcp.slack.com/mcp", auth="oauth", featured=True),
    ConnectorListing(
        id="notion", name="Notion", publisher="Notion", category="Productivity",
        tagline="Search, read and write pages and databases.",
        description="Notion's hosted server. OAuth; on Business and Enterprise plans a workspace owner can instead "
                    "create an MCP token (add with auth 'bearer').",
        capabilities=["Search Notion and connected sources", "Read, create and update pages",
                      "Create databases"],
        availability="Official hosted server",
        docs_url="https://developers.notion.com/guides/mcp/get-started-with-mcp",
        transport="streamable_http", url="https://mcp.notion.com/mcp", auth="oauth", featured=True),
    ConnectorListing(
        id="atlassian", name="Atlassian (Rovo MCP)", publisher="Atlassian", category="Project management",
        tagline="Work in Jira, Confluence, Bitbucket and Jira Service Management.",
        description="Rovo MCP server v2 (v1 users move to v2 on 2027-03-01). OAuth 2.1 respecting existing "
                    "Atlassian permissions.",
        capabilities=["Jira", "Confluence", "Bitbucket", "Jira Service Management", "Loom"],
        availability="Official Rovo MCP server",
        docs_url="https://support.atlassian.com/atlassian-rovo-mcp-server/docs/"
                 "getting-started-with-the-atlassian-remote-mcp-server/",
        transport="streamable_http", url="https://mcp.atlassian.com/v2/mcp", auth="oauth"),
    ConnectorListing(
        id="github", name="GitHub", publisher="GitHub", category="Development",
        tagline="Work with repositories, issues, pull requests and Actions.",
        description="Remote server with a personal access token as the bearer token. A local server also exists "
                    "(Docker image ghcr.io/github/github-mcp-server, stdio, admin keys).",
        capabilities=["Repositories", "Issues", "Pull requests", "Actions", "Code search"],
        availability="Official, local and remote",
        docs_url="https://github.com/github/github-mcp-server",
        transport="streamable_http", url="https://api.githubcopilot.com/mcp/", auth="bearer"),
    ConnectorListing(
        id="n8n", name="n8n", publisher="n8n", category="Automation",
        tagline="Find and run the workflows of your n8n instance.",
        description="Instance-level server of your n8n: copy the URL (ends in /mcp-server/http) from Settings > "
                    "Instance-level MCP > Connect a client. Bearer: the personal access token n8n generates there. A "
                    "local or plain-http n8n needs an admin key.",
        capabilities=["Search workflows", "Run MCP-enabled workflows", "Create and edit workflows and data tables"],
        availability="Official instance-level server",
        docs_url="https://docs.n8n.io/connect/connect-to-n8n-mcp-server",
        transport="streamable_http", url=None, auth="bearer"),
    ConnectorListing(
        id="supabase", name="Supabase", publisher="Supabase", category="Data",
        tagline="Query and manage Supabase databases and projects.",
        description="Supabase's remote server; sign in to Supabase and choose the organization. Scope it with "
                    "query parameters, e.g. ?project_ref=<ref>&read_only=true (a project URL can be generated in the "
                    "dashboard's MCP connection tab).",
        capabilities=["Database (SQL, tables, migrations)", "Docs search", "Projects", "Edge functions"],
        availability="Official",
        docs_url="https://github.com/supabase/mcp",
        transport="streamable_http", url="https://mcp.supabase.com/mcp", auth="oauth"),
    ConnectorListing(
        id="databricks", name="Databricks", publisher="Databricks", category="Data",
        tagline="Run SQL, Genie spaces and Unity Catalog functions.",
        description="Managed servers in your workspace, e.g. https://<workspace-hostname>/api/2.0/mcp/sql, "
                    "/api/2.0/mcp/genie/{genie_space_id}, /api/2.0/mcp/functions/{catalog}/{schema}/{function}. "
                    "A workspace admin enables Managed MCP Servers (public preview). " + _NO_DCR,
        capabilities=["Databricks SQL", "Genie spaces", "AI (vector) search", "Unity Catalog functions"],
        availability="Official managed servers, public preview",
        docs_url="https://docs.databricks.com/aws/generative-ai/mcp/managed-mcp",
        transport="streamable_http", url=None, auth="oauth"),
    ConnectorListing(
        id="shopify-catalog", name="Shopify Catalog", publisher="Shopify", category="Commerce",
        tagline="Search products across Shopify merchants.",
        description="Global Catalog MCP: product search across Shopify merchants (buyer side, not your store's "
                    "admin). Shopify requires every request to carry the agent's UCP profile URL in `meta`, which "
                    "this client does not send yet.",
        capabilities=["search_catalog", "lookup_catalog", "get_product"],
        availability="Official, specific capabilities (Catalog MCP)",
        docs_url="https://shopify.dev/docs/agents/catalog/global-catalog",
        transport="streamable_http", url="https://catalog.shopify.com/api/ucp/mcp", auth="none"),
]

_BY_ID = {item.id: item for item in LISTINGS}


def listing(listing_id: str) -> ConnectorListing | None:
    return _BY_ID.get(listing_id)


def catalog() -> list[ConnectorListing]:
    """Built-in apps, then featured listings, then store order."""
    return sorted(LISTINGS, key=lambda item: (not item.builtin, not item.featured))
