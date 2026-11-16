"""The workspace database app: `DatabaseApp` on its own, as a built-in connector of `ConnectorHub`, and its routes."""

from __future__ import annotations

import asyncio
import sqlite3

import pytest
from fastapi.testclient import TestClient

import agent
from business.connectors import ConnectorHub, InvalidConnector
from business.database import MAX_ROWS, DatabaseApp, DatabaseError
from business.schema import Column, ConnectorCreate, TableCreate
from tests.conftest import make_test_app
from tests.fakes import Chat, Embeddings, config

DB = "db-1"
CUSTOMERS = TableCreate(name="customers", columns=[Column(name="name", required=True), Column(name="email"),
                                                   Column(name="orders", type="integer")])


@pytest.fixture
def app(tmp_path) -> DatabaseApp:
    database = DatabaseApp(tmp_path / "databases")
    database.create_table(DB, CUSTOMERS)
    database.insert_many(DB, "customers", [{"name": "Rosa", "email": "rosa@cafe.example", "orders": 3},
                                           {"name": "Milo", "orders": 1}])
    return database


def install(hub: ConnectorHub, owner: str = "1", name: str = "Orders") -> str:
    request = ConnectorCreate(listing_id="workspace-database", name=name)
    return asyncio.run(hub.add(owner, request, admin=False)).id


# --- tables and rows -------------------------------------------------------------------------------


def test_tables_have_a_key_and_typed_columns(app):
    (table,) = app.tables(DB)
    assert (table.name, table.rows) == ("customers", 2)
    assert [(c.name, c.type, c.primary_key, c.required) for c in table.columns] == [
        ("id", "integer", True, False), ("name", "text", False, True), ("email", "text", False, False),
        ("orders", "integer", False, False)]


def test_rows_are_paged_with_their_keys(app):
    page = app.rows(DB, "customers", limit=1, offset=1)
    assert (page.columns, page.rowids, page.rows, page.total) == (
        ["id", "name", "email", "orders"], [2], [[2, "Milo", None, 1]], 2)


def test_update_and_delete_need_a_condition(app):
    assert app.update(DB, "customers", {"orders": 4}, {"name": "Rosa"}) == 1
    assert app.delete(DB, "customers", {"email": None}) == 1  # null matches IS NULL
    assert app.rows(DB, "customers").rows == [[1, "Rosa", "rosa@cafe.example", 4]]
    for where in ({}, None):
        with pytest.raises(DatabaseError, match="at least one column"):
            app.delete(DB, "customers", where)


def test_a_condition_on_an_unknown_column_is_refused_not_read_as_text(app):
    # SQLite reads an unknown double-quoted name as a string: "status" = 'status' would match every row.
    for change in (lambda: app.delete(DB, "customers", {"status": "status"}),
                   lambda: app.update(DB, "customers", {"orders": 0}, {"status": "status"}),
                   lambda: app.delete(DB, "customers", {"name": "Rosa", "nope": 1})):
        with pytest.raises(DatabaseError, match="No such column"):
            change()
    assert [row[3] for row in app.rows(DB, "customers").rows] == [3, 1]  # nothing was deleted or changed
    assert app.delete(DB, "customers", {"NAME": "Rosa"}) == 1  # column names are case-insensitive, as in SQLite
    assert app.delete(DB, "customers", {"rowid": 2}) == 1


def test_a_table_without_rowids_is_readable(app):
    app.query(DB, "CREATE TABLE codes (code TEXT PRIMARY KEY, label TEXT) WITHOUT ROWID", write=True)
    app.query(DB, "INSERT INTO codes VALUES ('A', 'first'), ('B', 'second')", write=True)
    page = app.rows(DB, "codes")
    assert (page.rowids, page.rows, page.total) == ([], [["A", "first"], ["B", "second"]], 2)
    assert app.export_csv(DB, "codes").splitlines() == ["code,label", "A,first", "B,second"]


@pytest.mark.parametrize("name", ["bad name", "1st", "sqlite_master", 'x"; DROP TABLE customers; --', ""])
def test_names_are_validated_never_interpolated(app, name):
    with pytest.raises(DatabaseError, match="Invalid"):
        app.rows(DB, name)
    with pytest.raises(DatabaseError, match="Invalid"):
        app.insert(DB, "customers", {name: "x"})
    assert app.table(DB, "customers").rows == 2


def test_a_missing_table_and_a_broken_constraint_are_reported(app):
    with pytest.raises(DatabaseError, match="no table"):
        app.rows(DB, "orders")
    with pytest.raises(DatabaseError, match="NOT NULL"):
        app.insert(DB, "customers", {"email": "x@y.example"})


# --- SQL -------------------------------------------------------------------------------------------


def test_a_read_query_cannot_change_anything(app):
    assert app.query(DB, "SELECT name FROM customers ORDER BY name").rows == [["Milo"], ["Rosa"]]
    for sql in ("DELETE FROM customers", "DROP TABLE customers", "INSERT INTO customers (name) VALUES ('x')",
                "ATTACH DATABASE 'other.db' AS other", "PRAGMA journal_mode = DELETE"):
        with pytest.raises(DatabaseError):
            app.query(DB, sql)
    assert app.table(DB, "customers").rows == 2


def test_a_write_statement_stays_inside_the_file(app, tmp_path):
    done = app.query(DB, "UPDATE customers SET orders = orders + 1", write=True)
    assert (done.changed, done.columns) == (2, [])
    app.query(DB, "ALTER TABLE customers ADD COLUMN city TEXT", write=True)
    assert "city" in [c.name for c in app.table(DB, "customers").columns]
    for sql in (f"ATTACH DATABASE '{(tmp_path / 'x.db').as_posix()}' AS x", "PRAGMA writable_schema = 1"):
        with pytest.raises(DatabaseError):
            app.query(DB, sql, write=True)
    assert not (tmp_path / "x.db").exists()


def test_query_results_are_capped(app):
    app.insert_many(DB, "customers", [{"name": f"c{i}"} for i in range(MAX_ROWS + 5)])
    result = app.query(DB, "SELECT id FROM customers")
    assert len(result.rows) == MAX_ROWS and result.truncated


# --- CSV -------------------------------------------------------------------------------------------


def test_csv_import_names_and_types_the_columns(app):
    data = b"Item Name,qty,Unit Price,id\nFlour,10,1.25,a\nSugar,,2,b\n"
    table = app.import_csv(DB, "stock", data)
    assert [(c.name, c.type) for c in table.columns] == [
        ("id", "integer"), ("Item_Name", "text"), ("qty", "integer"), ("Unit_Price", "real"), ("id_2", "text")]
    assert app.rows(DB, "stock").rows == [[1, "Flour", 10, 1.25, "a"], [2, "Sugar", None, 2.0, "b"]]
    assert app.export_csv(DB, "stock").splitlines()[:2] == ["id,Item_Name,qty,Unit_Price,id_2", "1,Flour,10,1.25,a"]
    with pytest.raises(DatabaseError, match="header row"):
        app.import_csv(DB, "empty", b"only,a,header\n")


def test_csv_import_keeps_codes_as_text(app):
    data = b"zip,account,amount,ratio,flag\n02134,1_000,12,0.5,nan\n00713,2_000,-7,3,inf\n"
    table = app.import_csv(DB, "codes", data)
    assert [(c.name, c.type) for c in table.columns][1:] == [
        ("zip", "text"), ("account", "text"), ("amount", "integer"), ("ratio", "real"), ("flag", "text")]
    assert app.rows(DB, "codes").rows[0] == [1, "02134", "1_000", 12, 0.5, "nan"]


def test_a_failed_csv_import_leaves_no_table(app, monkeypatch):
    def refuse(conn, name, rows):
        raise sqlite3.IntegrityError("constraint failed")
    monkeypatch.setattr(DatabaseApp, "_insert", staticmethod(refuse))
    with pytest.raises(DatabaseError, match="constraint failed"):
        app.import_csv(DB, "stock", b"item,qty\nFlour,3\n")
    monkeypatch.undo()
    assert [t.name for t in app.tables(DB)] == ["customers"]
    assert app.import_csv(DB, "stock", b"item,qty\nFlour,3\n").rows == 1  # the retry is not blocked


# --- as a connector ----------------------------------------------------------------------------------


def test_the_hub_installs_lists_and_calls_the_database(tmp_path):
    hub = ConnectorHub(tmp_path / "business.db", None, "http://localhost:8000")
    connector_id = install(hub)
    info = hub.get("1", connector_id)
    assert (info.transport, info.status, info.url, info.has_secret) == ("builtin", "connected", None, False)
    tools = asyncio.run(hub.tools("1", [connector_id]))
    assert {t.name for t in tools if t.read_only} == {"list_tables", "describe_table", "query"}
    assert {t.name for t in tools if not t.read_only} == {"create_table", "insert_rows", "update_rows",
                                                           "delete_rows", "execute"}
    assert info.tool_count == len(tools)

    def call(tool: str, **arguments):
        return asyncio.run(hub.call("1", connector_id, tool, arguments))

    assert call("list_tables").text == "The database has no tables yet."
    created = call("create_table", name="leads", columns=[{"name": "company"}, {"name": "value", "type": "real"}])
    assert created.text == "Created leads (0 rows): id integer key, company text, value real"
    assert call("insert_rows", table="leads", rows=[{"company": "Acme", "value": 1200.5}]).text.startswith("Inserted 1")
    assert call("query", sql="SELECT company, value FROM leads").text == "company | value\nAcme | 1200.5"
    assert call("update_rows", table="leads", set={"value": 900}, where={"company": "Acme"}).text == "Updated 1 row(s)."
    refused = call("query", sql="DELETE FROM leads")
    assert refused.is_error and "refused" in refused.text
    assert call("delete_rows", table="leads", where={}).is_error
    assert call("no_such_tool").is_error
    assert asyncio.run(hub.call("2", connector_id, "list_tables", {})).is_error  # another owner's database


def test_removing_the_connector_deletes_its_file_and_each_install_is_separate(tmp_path):
    hub = ConnectorHub(tmp_path / "business.db", None, "http://localhost:8000")
    first, second = install(hub), install(hub, name="Inventory")
    hub.databases.create_table(first, CUSTOMERS)
    assert hub.databases.tables(second) == []
    assert hub.database("1", first) is hub.databases and hub.database("2", first) is None
    assert hub.remove("1", first) and not hub.databases.path(first).exists()
    assert hub.databases.path(second).exists()


def test_builtin_apps_come_from_their_listing_only(tmp_path):
    hub = ConnectorHub(tmp_path / "business.db", None, "http://localhost:8000")
    with pytest.raises(InvalidConnector, match="store listing"):
        asyncio.run(hub.add("1", ConnectorCreate(name="x", transport="builtin"), admin=True))
    with pytest.raises(InvalidConnector, match="no URL"):
        asyncio.run(hub.add("1", ConnectorCreate(listing_id="workspace-database", name="x", url="https://x.example"),
                            admin=True))


# --- routes ------------------------------------------------------------------------------------------


def test_database_routes(tmp_path):
    hub = ConnectorHub(tmp_path / "business.db", None, "http://localhost:8000")
    app, key = make_test_app(assistant=agent.build(config(tmp_path), Chat([]), Embeddings()), connectors=hub)
    with TestClient(app) as client:
        client.headers["X-API-Key"] = key
        added = client.post("/v1/connectors", json={"listing_id": "workspace-database", "name": "Orders"})
        assert added.status_code == 201 and added.json()["data"]["status"] == "connected"
        base = f"/v1/databases/{added.json()['data']['id']}"
        created = client.post(f"{base}/tables", json=CUSTOMERS.model_dump())
        assert created.status_code == 201 and created.json()["data"]["columns"][0]["name"] == "id"
        rowid = client.post(f"{base}/tables/customers/rows", json={"values": {"name": "Rosa"}}).json()["data"]
        assert client.put(f"{base}/tables/customers/rows/{rowid}", json={"values": {"orders": 2}}).status_code == 204
        page = client.get(f"{base}/tables/customers/rows").json()["data"]
        assert (page["rowids"], page["rows"], page["total"]) == ([rowid], [[rowid, "Rosa", None, 2]], 1)
        selected = client.post(f"{base}/query", json={"sql": "SELECT count(*) AS n FROM customers"}).json()["data"]
        assert (selected["columns"], selected["rows"]) == (["n"], [[1]])
        refused = client.post(f"{base}/query", json={"sql": "DROP TABLE customers"})
        assert (refused.status_code, refused.json()["error"]["code"]) == (422, "invalid_database_request")
        imported = client.post(f"{base}/tables/import", data={"name": "stock"},
                               files={"file": ("stock.csv", b"item,qty\nFlour,3\n", "text/csv")})
        assert imported.status_code == 201 and imported.json()["data"]["rows"] == 1
        assert client.get(f"{base}/tables/stock/export").text.splitlines() == ["id,item,qty", "1,Flour,3"]
        assert client.delete(f"{base}/tables/customers/rows/{rowid}").status_code == 204
        assert client.delete(f"{base}/tables/customers/rows/{rowid}").status_code == 404
        assert client.delete(f"{base}/tables/stock").status_code == 204
        assert [t["name"] for t in client.get(f"{base}/tables").json()["data"]] == ["customers"]
        assert client.get("/v1/databases/unknown/tables").status_code == 404
