"""fake_models.py

A stand-in for the model servers, for local development and end-to-end tests
without GPUs or downloads. One stdlib HTTP server impersonates:

| Endpoint                    | Used by                 | Reply                                            |
|-----------------------------|-------------------------|--------------------------------------------------|
| `POST /v1/embeddings`       | library.search.Embedder | hashed bag-of-words vectors                      |
| `POST /v1/chat/completions` | agent.agent.ChatClient  | scripted: a tool call, then an answer citing [1] |

Chat: when the request offers tools and the last message is the user's, the
reply calls `list_documents` if the text starts with "list", else
`search_documents` with the text as query. After tool results it answers with
the line of excerpt [1] sharing the most words with the question, citing [1];
without a source [1] it repeats the start of the tool result.

*Usage:*
    uv run --no-sync python -m tests.e2e.fake_models --port 11435
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DIM = 256


def vector(text: str) -> list[float]:
    v = [0.0] * DIM
    for word in re.findall(r"\w+", text.lower()):
        if word not in ("search_query", "search_document"):
            v[int(hashlib.md5(word.encode()).hexdigest(), 16) % DIM] += 1
    norm = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / norm for x in v]


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _tool_call(text: str) -> dict:
    name, args = ("list_documents", {}) if text.lower().startswith("list") else ("search_documents", {"query": text})
    return {"role": "assistant", "content": None, "tool_calls": [
        {"id": "call_1", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}


def _answer(messages: list[dict]) -> dict:
    results = []
    for m in reversed(messages):
        if m["role"] != "tool":
            break
        results.insert(0, m["content"] or "")
    first = next((r for r in results if r.startswith("[1]")), None)
    question = _words(next((m["content"] for m in reversed(messages) if m["role"] == "user"), ""))
    if first:
        excerpt = first.split("\n\n[2]", 1)[0].splitlines()[1:] or [""]  # below the "[1] title" line
        line = max(excerpt, key=lambda x: len(question & _words(x)))
        content = f"According to the documents: {line.strip()} [1]"
    elif results:
        content = "Here is what I found:\n" + results[0][:800]
    else:
        content = "I could not find that in the documents."
    return {"role": "assistant", "content": content}


def chat(body: dict) -> dict:
    messages = body.get("messages", [])
    last = messages[-1] if messages else {"role": "user", "content": ""}
    asks = body.get("tools") and last["role"] == "user"
    message = _tool_call(last["content"]) if asks else _answer(messages)
    return {"id": "fake", "object": "chat.completion", "model": body.get("model", "fake"),
            "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5}}


class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, payload: dict) -> None:
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        if self.path == "/v1/embeddings":
            return self._send(200, {"object": "list", "data": [
                {"object": "embedding", "index": i, "embedding": vector(t)} for i, t in enumerate(body["input"])]})
        if self.path == "/v1/chat/completions":
            return self._send(200, chat(body))
        self._send(404, {"error": "not found"})

    def log_message(self, *args) -> None:  # quiet
        pass


def serve(port: int, host: str = "127.0.0.1") -> ThreadingHTTPServer:
    """Start the server in a background thread and return it (`.shutdown()` stops it)."""
    server = ThreadingHTTPServer((host, port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def main() -> None:
    parser = argparse.ArgumentParser(description="Fake OpenAI-compatible model server")
    parser.add_argument("--port", type=int, default=11435)
    args = parser.parse_args()
    server = serve(args.port)
    print(f"fake models on http://127.0.0.1:{args.port}", flush=True)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
