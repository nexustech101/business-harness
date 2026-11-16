"""business/database.py

The workspace database app: a built-in connector (`business.catalog` listing `workspace-database`) that gives the
owner their own SQLite databases. Each installed connector is one file, `<directory>/<connector id>.db`; the
dashboard manages it through `api/routes/databases.py`, assistants through the tools below (reads always run,
writes follow the assistant's policy like any connector tool).

| Tool             | read_only | Does                                                              |
|------------------|-----------|-------------------------------------------------------------------|
| `list_tables`    | yes       | every table with its columns and row count                        |
| `describe_table` | yes       | one table's columns                                               |
| `query`          | yes       | one SELECT statement, at most `MAX_ROWS` rows                     |
| `create_table`   | no        | a table with typed columns (an `id` key is added)                 |
| `insert_rows`    | no        | rows as objects keyed by column name                              |
| `update_rows`    | no        | set columns on the rows matching every `where` column             |
| `delete_rows`    | no        | delete the rows matching every `where` column                     |
| `execute`        | no        | one other SQL statement (ALTER, CREATE INDEX, UPDATE ... WHERE)   |

Safety: table and column names are validated identifiers (never interpolated as given), `where` columns must
exist in the table (SQLite would read an unknown quoted name as a string, turning the condition into a
constant), values are always bound parameters, and every connection runs under a SQLite authorizer: reads may
only SELECT, writes may not ATTACH other files, load extensions or change PRAGMAs. A statement is stopped after
`TIMEOUT_S`, a file grows to at most `MAX_BYTES`.

*Usage:*
>>> app = DatabaseApp(Path("data/databases"))
>>> app.create_table("c1", TableCreate(name="customers", columns=[Column(name="email", type="text")]))
>>> app.insert("c1", "customers", {"email": "a@b.co"})
>>> app.query("c1", "SELECT email FROM customers").rows
[['a@b.co']]
"""

from __future__ import annotations

import csv
import io
import re
import sqlite3
import time
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ValidationError

from business.schema import Column, ColumnType, ConnectorTool, QueryResult, RowPage, TableCreate, TableInfo

MAX_ROWS = 500  # rows one query or page returns
MAX_BYTES = 512 * 1024 * 1024  # per database file
MAX_IMPORT_ROWS = 50_000
TIMEOUT_S = 5.0  # per statement
PAGE_SIZE = 4096
KEY = "id"  # the key column `create_table` adds
ROWID = "rowid"  # SQLite's own row key: what the row routes address a row by

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")
_CONNECTOR_ID = re.compile(r"^[A-Za-z0-9-]{1,64}$")
# Numbers as a spreadsheet writes them. Anything else stays text: '02134' is a ZIP code, not 2134.
_INTEGER = re.compile(r"-?(0|[1-9]\d{0,17})")
_DECIMAL = re.compile(r"-?(0|[1-9]\d{0,17})(\.\d+)?")
_TYPES: dict[str, ColumnType] = {"TEXT": "text", "INTEGER": "integer", "REAL": "real", "DATE": "date",
                                 "BOOLEAN": "boolean"}

_READ_ACTIONS = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION, sqlite3.SQLITE_RECURSIVE}
_DENIED_WRITES = {sqlite3.SQLITE_ATTACH, sqlite3.SQLITE_DETACH}
_PRAGMAS = {"table_info"}  # the only PRAGMA a statement may use (how `_columns` reads a table)


class DatabaseError(ValueError):
    """A request the database cannot run: a bad name, SQL that fails or is not allowed (422)."""


# --- Names, conditions and authorizers -------------------------------------------------------------------


def identifier(name: object, what: str = "name") -> str:
    """`name` as a quoted SQL identifier; `DatabaseError` unless it is letters, digits and `_` (not `sqlite_...`)."""
    if not isinstance(name, str) or not _IDENTIFIER.match(name) or name.lower().startswith("sqlite_"):
        raise DatabaseError(f"Invalid {what} {name!r}: use letters, digits and _ (starting with a letter or _).")
    return f'"{name}"'


def _condition(where: object, columns: Iterable[str]) -> tuple[str, list]:
    """`{column: value}` as `"a" = ? AND "b" IS NULL` with its parameters. `DatabaseError` when it is empty (no
    unfiltered updates) or names a column that is not one of `columns`."""
    if not isinstance(where, dict) or not where:
        raise DatabaseError("`where` must name at least one column, e.g. {\"id\": 3}.")
    known = {column.lower() for column in columns}
    unknown = [name for name in where if not isinstance(name, str) or name.lower() not in known]
    if unknown:
        raise DatabaseError(f"No such column: {', '.join(map(repr, unknown))}.")
    clauses = [f"{identifier(name, 'column')} IS NULL" if value is None else f"{identifier(name, 'column')} = ?"
               for name, value in where.items()]
    return " AND ".join(clauses), [value for value in where.values() if value is not None]


def _pragma_allowed(action: int, name: object) -> bool:
    return action == sqlite3.SQLITE_PRAGMA and name in _PRAGMAS


def _read_only(action: int, name: object = None, *_: object) -> int:
    """Authorizer of read connections: SELECT and nothing else."""
    return sqlite3.SQLITE_OK if action in _READ_ACTIONS or _pragma_allowed(action, name) else sqlite3.SQLITE_DENY


def _no_escape(action: int, name: object = None, *_: object) -> int:
    """Authorizer of write connections: everything inside this file, no other files and no PRAGMA changes."""
    if action == sqlite3.SQLITE_PRAGMA:
        return sqlite3.SQLITE_OK if _pragma_allowed(action, name) else sqlite3.SQLITE_DENY
    return sqlite3.SQLITE_DENY if action in _DENIED_WRITES else sqlite3.SQLITE_OK


def _cell(value: object) -> object:
    """A value as JSON can carry it (bytes as a size note)."""
    return f"[{len(value)} bytes]" if isinstance(value, bytes) else value


def _cells(rows: Iterable[tuple]) -> list[list]:
    return [[_cell(value) for value in row] for row in rows]


# --- The app ---------------------------------------------------------------------------------------------


class DatabaseApp:
    def __init__(self, directory: Path):
        self.directory = Path(directory)

    # --- files and connections -----------------------------------------------------------------

    def path(self, connector_id: str) -> Path:
        if not _CONNECTOR_ID.match(connector_id):
            raise DatabaseError("Invalid database id.")
        return self.directory / f"{connector_id}.db"

    def remove(self, connector_id: str) -> None:
        """Delete the database file (the connector was removed)."""
        for suffix in ("", "-wal", "-shm", "-journal"):
            Path(str(self.path(connector_id)) + suffix).unlink(missing_ok=True)

    @contextmanager
    def _connect(self, connector_id: str, authorizer: Callable[..., int]) -> Iterator[sqlite3.Connection]:
        """A connection per operation under `authorizer`, committed on success; sqlite errors become
        `DatabaseError` with SQLite's message."""
        self.directory.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path(connector_id))
        try:
            conn.execute(f"PRAGMA max_page_count = {MAX_BYTES // PAGE_SIZE}")
            deadline = time.monotonic() + TIMEOUT_S
            conn.set_progress_handler(lambda: int(time.monotonic() > deadline), 10_000)
            conn.set_authorizer(authorizer)
            with conn:
                yield conn
        except sqlite3.Error as exc:
            message = "it took too long" if "interrupted" in str(exc) else str(exc)
            raise DatabaseError(f"The database refused the statement: {message}.") from exc
        finally:
            conn.close()

    def _read(self, connector_id: str):
        return self._connect(connector_id, _read_only)

    def _write(self, connector_id: str):
        return self._connect(connector_id, _no_escape)

    # --- tables --------------------------------------------------------------------------------

    def tables(self, connector_id: str) -> list[TableInfo]:
        with self._read(connector_id) as conn:
            names = [r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
            return [self._table(conn, name) for name in names]

    def table(self, connector_id: str, name: str) -> TableInfo:
        with self._read(connector_id) as conn:
            return self._table(conn, name)

    @staticmethod
    def _columns(conn: sqlite3.Connection, name: str) -> list[Column]:
        """The table's columns; `DatabaseError` when there is no such table."""
        identifier(name, "table")
        columns = [Column(name=r[1], type=_TYPES.get((r[2] or "").upper(), "text"), required=bool(r[3]),
                          primary_key=bool(r[5])) for r in conn.execute("SELECT * FROM pragma_table_info(?)", (name,))]
        if not columns:
            raise DatabaseError(f"There is no table {name!r}.")
        return columns

    @classmethod
    def _table(cls, conn: sqlite3.Connection, name: str) -> TableInfo:
        columns = cls._columns(conn, name)
        count = conn.execute(f"SELECT count(*) FROM {identifier(name, 'table')}").fetchone()[0]
        return TableInfo(name=name, columns=columns, rows=count)

    def create_table(self, connector_id: str, request: TableCreate) -> TableInfo:
        with self._write(connector_id) as conn:
            self._create(conn, request)
            return self._table(conn, request.name)

    @staticmethod
    def _create(conn: sqlite3.Connection, request: TableCreate) -> None:
        columns = [c for c in request.columns if c.name.lower() != KEY]
        if not columns:
            raise DatabaseError("A table needs at least one column besides its id.")
        definitions = [f"{identifier(KEY)} INTEGER PRIMARY KEY AUTOINCREMENT"]
        definitions += [f"{identifier(c.name, 'column')} {c.type.upper()}" + (" NOT NULL" if c.required else "")
                        for c in columns]
        conn.execute(f"CREATE TABLE {identifier(request.name, 'table')} ({', '.join(definitions)})")

    def drop_table(self, connector_id: str, name: str) -> None:
        with self._write(connector_id) as conn:
            self._columns(conn, name)  # DatabaseError when it does not exist
            conn.execute(f"DROP TABLE {identifier(name, 'table')}")

    # --- rows ------------------------------------------------------------------------------------

    def rows(self, connector_id: str, name: str, limit: int = 50, offset: int = 0) -> RowPage:
        """A page of rows in key order, each with its rowid (what `update` and `delete` take). A table created
        WITHOUT ROWID is read as it is, with no `rowids`: its rows can be changed through SQL only."""
        quoted, page = identifier(name, "table"), (min(limit, MAX_ROWS), offset)
        with self._read(connector_id) as conn:
            table = self._table(conn, name)
            try:
                keyed = conn.execute(f"SELECT rowid, * FROM {quoted} ORDER BY rowid LIMIT ? OFFSET ?", page).fetchall()
                rowids, rows = [row[0] for row in keyed], [row[1:] for row in keyed]
            except sqlite3.OperationalError:  # no such column: rowid
                rowids, rows = [], conn.execute(f"SELECT * FROM {quoted} LIMIT ? OFFSET ?", page).fetchall()
        return RowPage(columns=[c.name for c in table.columns], rowids=rowids, rows=_cells(rows), total=table.rows)

    def insert(self, connector_id: str, name: str, values: dict) -> int:
        """The new row's rowid."""
        return self.insert_many(connector_id, name, [values])[-1]

    def insert_many(self, connector_id: str, name: str, rows: list[dict]) -> list[int]:
        """The new rows' rowids; all rows are inserted, or none."""
        with self._write(connector_id) as conn:
            return self._insert(conn, name, rows)

    @staticmethod
    def _insert(conn: sqlite3.Connection, name: str, rows: list[dict]) -> list[int]:
        if not isinstance(rows, list) or not rows or not all(isinstance(r, dict) and r for r in rows):
            raise DatabaseError("Give at least one row, each an object of column: value.")
        quoted, ids = identifier(name, "table"), []
        for row in rows:
            columns = ", ".join(identifier(k, "column") for k in row)
            cursor = conn.execute(f"INSERT INTO {quoted} ({columns}) VALUES ({', '.join('?' * len(row))})",
                                  list(row.values()))
            ids.append(cursor.lastrowid)
        return ids

    def update(self, connector_id: str, name: str, values: dict, where: dict) -> int:
        """Rows changed."""
        if not isinstance(values, dict) or not values:
            raise DatabaseError("Give the columns to change as an object of column: value.")
        assignments = ", ".join(f"{identifier(k, 'column')} = ?" for k in values)
        with self._write(connector_id) as conn:
            condition, params = self._where(conn, name, where)
            return conn.execute(f"UPDATE {identifier(name, 'table')} SET {assignments} WHERE {condition}",
                                [*values.values(), *params]).rowcount

    def delete(self, connector_id: str, name: str, where: dict) -> int:
        """Rows deleted."""
        with self._write(connector_id) as conn:
            condition, params = self._where(conn, name, where)
            return conn.execute(f"DELETE FROM {identifier(name, 'table')} WHERE {condition}", params).rowcount

    @classmethod
    def _where(cls, conn: sqlite3.Connection, name: str, where: object) -> tuple[str, list]:
        """`where` as SQL over the table's own columns (and its rowid)."""
        return _condition(where, [ROWID, *(c.name for c in cls._columns(conn, name))])

    # --- SQL -------------------------------------------------------------------------------------

    def query(self, connector_id: str, sql: str, write: bool = False) -> QueryResult:
        """One statement. Without `write` only SELECT is allowed; with it everything but ATTACH and PRAGMA."""
        if not isinstance(sql, str) or not sql.strip():
            raise DatabaseError("`sql` is required.")
        with (self._write if write else self._read)(connector_id) as conn:
            cursor = conn.execute(sql)
            rows = cursor.fetchmany(MAX_ROWS + 1) if cursor.description else []
            return QueryResult(columns=[d[0] for d in cursor.description or []], rows=_cells(rows[:MAX_ROWS]),
                               truncated=len(rows) > MAX_ROWS, changed=max(cursor.rowcount, 0) if write else 0)

    # --- CSV -------------------------------------------------------------------------------------

    def import_csv(self, connector_id: str, name: str, data: bytes) -> TableInfo:
        """A new table from a CSV file: the first row names the columns, their types follow from the values.
        The table and its rows are written in one transaction: a failed import leaves nothing behind."""
        header, body = _csv_records(data)
        cells = [[(row[i].strip() if i < len(row) else "") for row in body] for i in range(len(header))]
        columns = [Column(name=h, type=_infer(values)) for h, values in zip(header, cells, strict=True)]
        rows = [{c.name: _typed(values[r], c.type) for c, values in zip(columns, cells, strict=True)}
                for r in range(len(body))]
        with self._write(connector_id) as conn:
            conn.execute("BEGIN")  # CREATE TABLE would otherwise commit on its own
            self._create(conn, TableCreate(name=name, columns=columns))
            self._insert(conn, name, rows)
            return self._table(conn, name)

    def export_csv(self, connector_id: str, name: str) -> str:
        out = io.StringIO()
        writer = csv.writer(out)
        with self._read(connector_id) as conn:
            writer.writerow([c.name for c in self._columns(conn, name)])
            writer.writerows(conn.execute(f"SELECT * FROM {identifier(name, 'table')}"))
        return out.getvalue()

    # --- assistant tools -----------------------------------------------------------------------

    def tools(self, connector_id: str) -> list[ConnectorTool]:
        return [ConnectorTool(connector_id=connector_id, name=name, description=tool.description,
                              read_only=tool.read_only, input_schema=tool.parameters)
                for name, tool in TOOLS.items()]

    def call(self, connector_id: str, tool: str, arguments: dict) -> str:
        """The text an assistant reads; `DatabaseError` for bad arguments or SQL, `KeyError` for an unknown tool."""
        return TOOLS[tool].run(self, connector_id, arguments)


# --- CSV helpers -------------------------------------------------------------------------------------------


def _csv_records(data: bytes) -> tuple[list[str], list[list[str]]]:
    """(column names, data rows) of a CSV file; `DatabaseError` when it is not CSV, has no data or is too long."""
    try:
        records = list(csv.reader(io.StringIO(data.decode("utf-8-sig"))))
    except (UnicodeDecodeError, csv.Error) as exc:
        raise DatabaseError(f"The file is not UTF-8 CSV: {exc}.") from exc
    records = [r for r in records if any(cell.strip() for cell in r)]
    if len(records) < 2:
        raise DatabaseError("The CSV needs a header row and at least one data row.")
    if len(records) - 1 > MAX_IMPORT_ROWS:
        raise DatabaseError(f"The CSV has more than {MAX_IMPORT_ROWS:,} rows.")
    return _column_names(records[0]), records[1:]


def _column_names(header: list[str]) -> list[str]:
    """CSV headers as unique identifiers: other characters become `_`, `id` and repeats get a suffix."""
    names: list[str] = []
    for i, raw in enumerate(header):
        name = re.sub(r"[^A-Za-z0-9_]+", "_", raw.strip()).strip("_")[:50] or f"column_{i + 1}"
        if name[0].isdigit() or name.lower().startswith("sqlite_"):
            name = f"c_{name}"
        base, n = name, 2
        while name.lower() in {x.lower() for x in names} | {KEY}:
            name, n = f"{base}_{n}", n + 1
        names.append(name)
    return names


def _infer(values: list[str]) -> ColumnType:
    """integer or real when every non-empty value is written as a plain number, else text."""
    present = [v for v in values if v != ""]
    if present and all(_INTEGER.fullmatch(v) for v in present):
        return "integer"
    if present and all(_DECIMAL.fullmatch(v) for v in present):
        return "real"
    return "text"


def _typed(value: str, kind: ColumnType) -> object:
    if value == "":
        return None
    return int(value) if kind == "integer" else float(value) if kind == "real" else value


# --- Assistant tools ---------------------------------------------------------------------------------------


def _validated[M: BaseModel](model: type[M], arguments: dict) -> M:
    try:
        return model.model_validate(arguments)
    except ValidationError as exc:
        error = exc.errors()[0]
        raise DatabaseError(f"{'.'.join(map(str, error['loc'])) or 'arguments'}: {error['msg']}") from exc


def _describe(table: TableInfo) -> str:
    columns = ", ".join(f"{c.name} {c.type}" + (" key" if c.primary_key else "") for c in table.columns)
    return f"{table.name} ({table.rows} rows): {columns}"


def _result_text(result: QueryResult) -> str:
    if not result.rows:
        return "No rows."
    lines = [" | ".join(result.columns)]
    lines += [" | ".join("" if v is None else str(v) for v in row) for row in result.rows]
    if result.truncated:
        lines.append(f"[only the first {MAX_ROWS} rows; narrow the query or add LIMIT/OFFSET]")
    return "\n".join(lines)


def _list_tables(app: DatabaseApp, connector_id: str, args: dict) -> str:
    return "\n".join(_describe(t) for t in app.tables(connector_id)) or "The database has no tables yet."


def _describe_table(app: DatabaseApp, connector_id: str, args: dict) -> str:
    return _describe(app.table(connector_id, args.get("table")))


def _query(app: DatabaseApp, connector_id: str, args: dict) -> str:
    return _result_text(app.query(connector_id, args.get("sql")))


def _create_table(app: DatabaseApp, connector_id: str, args: dict) -> str:
    return f"Created {_describe(app.create_table(connector_id, _validated(TableCreate, args)))}"


def _insert_rows(app: DatabaseApp, connector_id: str, args: dict) -> str:
    ids = app.insert_many(connector_id, args.get("table"), args.get("rows"))
    return f"Inserted {len(ids)} row(s) into {args.get('table')} (ids {ids[0]}..{ids[-1]})."


def _update_rows(app: DatabaseApp, connector_id: str, args: dict) -> str:
    return f"Updated {app.update(connector_id, args.get('table'), args.get('set'), args.get('where'))} row(s)."


def _delete_rows(app: DatabaseApp, connector_id: str, args: dict) -> str:
    return f"Deleted {app.delete(connector_id, args.get('table'), args.get('where'))} row(s)."


def _execute(app: DatabaseApp, connector_id: str, args: dict) -> str:
    result = app.query(connector_id, args.get("sql"), write=True)
    return _result_text(result) if result.columns else f"Done; {result.changed} row(s) changed."


@dataclass(frozen=True)
class DatabaseTool:
    description: str
    parameters: dict
    run: Callable[[DatabaseApp, str, dict], str]
    read_only: bool = False


_TABLE = {"type": "string", "description": "Table name."}
_ROW = {"type": "object", "description": "column name -> value"}
_SQL = {"type": "object", "properties": {"sql": {"type": "string"}}, "required": ["sql"]}
_COLUMN = {"type": "object", "properties": {"name": {"type": "string"},
                                            "type": {"type": "string", "enum": list(_TYPES.values())},
                                            "required": {"type": "boolean"}}, "required": ["name"]}

TOOLS: dict[str, DatabaseTool] = {
    "list_tables": DatabaseTool("Every table of the database with its columns, types and row count.",
                                {"type": "object", "properties": {}}, _list_tables, read_only=True),
    "describe_table": DatabaseTool("One table's columns and row count.",
                                   {"type": "object", "properties": {"table": _TABLE}, "required": ["table"]},
                                   _describe_table, read_only=True),
    "query": DatabaseTool(f"Run one SELECT statement (SQLite) and return its rows, at most {MAX_ROWS}.", _SQL,
                          _query, read_only=True),
    "create_table": DatabaseTool("Create a table. An integer `id` key is added automatically.",
                                 {"type": "object", "properties": {
                                     "name": _TABLE, "columns": {"type": "array", "items": _COLUMN}},
                                  "required": ["name", "columns"]}, _create_table),
    "insert_rows": DatabaseTool("Insert rows into a table.",
                                {"type": "object", "properties": {"table": _TABLE,
                                                                  "rows": {"type": "array", "items": _ROW}},
                                 "required": ["table", "rows"]}, _insert_rows),
    "update_rows": DatabaseTool("Set columns on the rows where every `where` column equals its value.",
                                {"type": "object", "properties": {"table": _TABLE, "set": _ROW, "where": _ROW},
                                 "required": ["table", "set", "where"]}, _update_rows),
    "delete_rows": DatabaseTool("Delete the rows where every `where` column equals its value.",
                                {"type": "object", "properties": {"table": _TABLE, "where": _ROW},
                                 "required": ["table", "where"]}, _delete_rows),
    "execute": DatabaseTool("Run one other SQL statement that changes the database (ALTER TABLE, CREATE INDEX, an "
                            "UPDATE or DELETE with its own WHERE, DROP TABLE).", _SQL, _execute),
}
