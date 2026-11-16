"""Workspace databases: the tables and rows of an installed `workspace-database` connector (business/database.py).

A database is created by adding the built-in listing on `POST /v1/connectors` and deleted by removing that
connector. Every route works in the calling key's own workspace; another key's database is `404`.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile

from api.deps import MB, ClientDep, ConnectorsDep, SettingsDep, business_owner, read_upload, require_api_key
from api.errors import responses
from business.database import DatabaseApp
from business.schema import QueryRequest, QueryResult, RowPage, RowWrite, TableCreate, TableInfo
from core.schema import Envelope

router = APIRouter(prefix="/v1/databases/{connector_id}", tags=["Databases"],
                   dependencies=[Depends(require_api_key)], responses=responses(401, 404, 422))


def database(connector_id: str, key: ClientDep, hub: ConnectorsDep) -> DatabaseApp:
    app = hub.database(business_owner(key), connector_id)
    if app is None:
        raise HTTPException(404, "Database not found.")
    return app


DatabaseDep = Annotated[DatabaseApp, Depends(database)]


@router.get("/tables", response_model=Envelope[list[TableInfo]])
def tables(connector_id: str, db: DatabaseDep) -> Envelope[list[TableInfo]]:
    """Every table with its columns and row count."""
    return Envelope(data=db.tables(connector_id))


@router.post("/tables", response_model=Envelope[TableInfo], status_code=201)
def create_table(connector_id: str, body: TableCreate, db: DatabaseDep) -> Envelope[TableInfo]:
    """Create a table; an integer `id` key column is added."""
    return Envelope(data=db.create_table(connector_id, body))


@router.post("/tables/import", response_model=Envelope[TableInfo], status_code=201, responses=responses(413))
async def import_table(connector_id: str, db: DatabaseDep, settings: SettingsDep,
                       name: Annotated[str, Form(min_length=1, max_length=63, description="The new table's name.")],
                       file: Annotated[UploadFile, File(description="UTF-8 CSV with a header row.")],
                       ) -> Envelope[TableInfo]:
    """A new table from a CSV file: the header names the columns, their types follow from the values."""
    data = await read_upload(file, settings.max_upload_mb * MB)
    return Envelope(data=db.import_csv(connector_id, name, data))


@router.delete("/tables/{table}", status_code=204)
def drop_table(connector_id: str, table: str, db: DatabaseDep) -> Response:
    """Delete a table with all its rows."""
    db.drop_table(connector_id, table)
    return Response(status_code=204)


@router.get("/tables/{table}/rows", response_model=Envelope[RowPage])
def rows(connector_id: str, table: str, db: DatabaseDep, limit: Annotated[int, Query(ge=1, le=500)] = 50,
         offset: Annotated[int, Query(ge=0)] = 0) -> Envelope[RowPage]:
    """A page of rows in key order; `rowids` are the keys the row routes take."""
    return Envelope(data=db.rows(connector_id, table, limit, offset))


@router.get("/tables/{table}/export", response_class=Response,
            responses={200: {"content": {"text/csv": {}}, "description": "The table as CSV"}})
def export_table(connector_id: str, table: str, db: DatabaseDep) -> Response:
    """The whole table as CSV, header first."""
    return Response(db.export_csv(connector_id, table), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{table}.csv"'})


@router.post("/tables/{table}/rows", response_model=Envelope[int], status_code=201)
def insert_row(connector_id: str, table: str, body: RowWrite, db: DatabaseDep) -> Envelope[int]:
    """Insert one row; returns its rowid."""
    return Envelope(data=db.insert(connector_id, table, body.values))


@router.put("/tables/{table}/rows/{rowid}", status_code=204)
def update_row(connector_id: str, table: str, rowid: int, body: RowWrite, db: DatabaseDep) -> Response:
    """Set columns of one row."""
    if not db.update(connector_id, table, body.values, {"rowid": rowid}):
        raise HTTPException(404, "Row not found.")
    return Response(status_code=204)


@router.delete("/tables/{table}/rows/{rowid}", status_code=204)
def delete_row(connector_id: str, table: str, rowid: int, db: DatabaseDep) -> Response:
    if not db.delete(connector_id, table, {"rowid": rowid}):
        raise HTTPException(404, "Row not found.")
    return Response(status_code=204)


@router.post("/query", response_model=Envelope[QueryResult])
def query(connector_id: str, body: QueryRequest, db: DatabaseDep) -> Envelope[QueryResult]:
    """Run one SQL statement: a SELECT, or with `write` a statement that changes the database."""
    return Envelope(data=db.query(connector_id, body.sql, body.write))
