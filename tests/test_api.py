"""API behaviour around the upload route with a fake parser: auth, keys, limits, errors, the job gate."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import agent
from core.config import get_settings
from core.parser import ConversionFailed
from tests.conftest import make_test_app
from tests.fakes import Embeddings, blank_pdf, config, fake_parser

PDF = blank_pdf(1)
UPLOAD = "/v1/library/documents"


@pytest.fixture
def api(tmp_path):
    parser = fake_parser("page text")
    settings = get_settings().model_copy(update={"library_rate_calls": 4, "max_upload_mb": 1})
    app, key = make_test_app(settings, parser=parser, assistant=agent.build(config(tmp_path), None, Embeddings()))
    with TestClient(app) as client:
        yield SimpleNamespace(client=client, key=key, parser=parser, headers={"X-API-Key": key})


def upload(name="contract.pdf", data=PDF):
    return {"file": (name, data, "application/pdf")}


def test_health_is_public_and_reports_the_parser(api):
    r = api.client.get("/health")
    assert r.status_code == 200 and r.json()["data"] == {"status": "ok", "docling_loaded": True}
    api.parser.loaded = False
    assert api.client.get("/health").json()["data"]["status"] == "degraded"


@pytest.mark.parametrize("headers", [{}, {"X-API-Key": "ak_not-a-real-key"}])
def test_routes_require_a_valid_key(api, headers):
    r = api.client.post(UPLOAD, files=upload(), headers=headers)
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthorized"
    assert r.headers["X-Request-ID"]


def test_upload_returns_the_envelope_and_a_request_id(api):
    r = api.client.post(UPLOAD, files=upload(), headers={**api.headers, "X-Request-ID": "req-1"})
    assert r.status_code == 201, r.text
    assert r.json()["data"]["title"] == "contract" and r.headers["X-Request-ID"] == "req-1"


def test_upload_rejects_unsupported_empty_and_oversized_files(api):
    r = api.client.post(UPLOAD, files=upload("notes.docx", b"PK\x03\x04"), headers=api.headers)
    assert (r.status_code, r.json()["error"]["code"]) == (415, "unsupported_media_type")
    assert "application/pdf" in r.json()["error"]["details"]["supported"]
    assert api.client.post(UPLOAD, files=upload(data=b""), headers=api.headers).status_code == 400
    big = b"%PDF-" + b"0" * (2 * 1024 * 1024)
    r = api.client.post(UPLOAD, files=upload(data=big), headers=api.headers)
    assert (r.status_code, r.json()["error"]["code"]) == (413, "payload_too_large")


def test_an_unreadable_document_is_422(api):
    async def unreadable(data, filename):
        raise ConversionFailed("No text could be read from the document.")
    api.parser.parse = unreadable
    r = api.client.post(UPLOAD, files=upload(), headers=api.headers)
    assert (r.status_code, r.json()["error"]["code"]) == (422, "unreadable_document")


def test_uploads_are_rate_limited_per_key(api):
    statuses = [api.client.post(UPLOAD, files=upload(), headers=api.headers).status_code for _ in range(5)]
    assert statuses == [201, 200, 200, 200, 429]  # the same file again is 200; the fifth call is over the limit
    r = api.client.post(UPLOAD, files=upload(), headers=api.headers)
    assert r.json()["error"]["code"] == "rate_limited" and int(r.headers["Retry-After"]) > 0


def test_key_management_requires_admin(api):
    r = api.client.post("/api-keys", json={"name": "client-app"}, headers=api.headers)
    assert r.status_code == 201
    client_key = r.json()["data"]["key"]
    assert client_key.startswith("ak_")
    assert "key_hash" not in r.json()["data"]["api_key"]

    client_headers = {"X-API-Key": client_key}
    assert api.client.get("/auth/me", headers=client_headers).json()["data"]["name"] == "client-app"
    assert api.client.get("/api-keys", headers=client_headers).status_code == 403
    assert api.client.post("/api-keys", json={"name": "x"}, headers=client_headers).status_code == 403

    key_id = r.json()["data"]["api_key"]["id"]
    assert api.client.delete(f"/api-keys/{key_id}", headers=api.headers).status_code == 204
    assert api.client.get("/auth/me", headers=client_headers).status_code == 401
    assert api.client.delete(f"/api-keys/{key_id}", headers=api.headers).status_code == 404


def test_unauthenticated_key_creation_is_off_by_default(api):
    assert api.client.post("/api-keys", json={"name": "attacker"}).status_code == 401


def _multipart(size: int, chunk: int = 64 * 1024):
    """A multipart upload (field `file`) streamed in chunks, without a Content-Length header."""
    boundary = "b0undary"
    yield (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"big.txt\"\r\n"
           "Content-Type: text/plain\r\n\r\nnotes ").encode()
    for _ in range(size // chunk):
        yield b"0" * chunk
    yield f"\r\n--{boundary}--\r\n".encode()


def test_body_limit_counts_bytes_without_content_length(api):
    headers = {**api.headers, "Content-Type": "multipart/form-data; boundary=b0undary"}
    r = api.client.post(UPLOAD, content=_multipart(2 * 1024 * 1024), headers=headers)
    assert "content-length" not in {k.lower() for k in r.request.headers}
    assert r.status_code == 413, r.text
    assert r.json()["error"]["code"] == "payload_too_large"
    r = api.client.post(UPLOAD, content=_multipart(256 * 1024), headers=headers)
    assert r.status_code == 201, r.text  # under the 1 MB test limit


def test_uploads_beyond_running_and_queued_jobs_are_refused(api):
    gate = api.client.app.state.jobs
    gate.held = gate.capacity  # every slot running or queued
    r = api.client.post(UPLOAD, files=upload(), headers=api.headers)
    assert r.status_code == 503 and r.json()["error"]["code"] == "busy"
    assert r.headers["Retry-After"] == "30"
    gate.held = 0
    assert api.client.post(UPLOAD, files=upload(), headers=api.headers).status_code == 201
    assert gate.held == 0  # the slot is released after the request


def test_job_gate_runs_at_most_n_and_queues_the_rest():
    import asyncio

    from core.jobs import JobGate

    async def scenario():
        gate, running, peak, release = JobGate(running=2, queued=1), 0, 0, asyncio.Event()

        async def job():
            nonlocal running, peak
            async with gate.slot():
                running += 1
                peak = max(peak, running)
                await release.wait()
                running -= 1

        tasks = [asyncio.create_task(job()) for _ in range(4)]
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)  # only the refused job can finish first
        at_refusal = running, gate.held
        release.set()
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return at_refusal, peak, [type(r).__name__ for r in results], gate.held

    at_refusal, peak, results, held = asyncio.run(scenario())
    assert at_refusal == (2, 3)  # 2 running + 1 queued when the 4th is refused
    assert peak == 2 and results.count("Busy") == 1 and held == 0
