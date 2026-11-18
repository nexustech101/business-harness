# Third-party licenses

What this project runs on, under which license, and what that means when the
system is delivered to a client. The project's own code (`api/`, `core/`,
`library/`, `agent/`, `business/`, `scripts/`, `tests/`, `web/`) is not covered here; its owner sets its license.

Versions are the ones locked in `uv.lock` and `web/package-lock.json`. Licenses are taken from each
package's own metadata and license files (regenerate the list with the
command at the end), and from the model cards for model weights.

## Summary

| | Risk for commercial delivery |
|---|---|
| Python packages | None found. All are permissive (MIT, BSD, Apache-2.0, PSF, MIT-CMU). Keep their notices when you redistribute them. |
| Dashboard (npm) packages | None found. MIT and ISC; the bundled Inter font is OFL-1.1. `web/dist` contains their code: keep their notices when you deliver it. |
| Docling layout model, RapidOCR models, Qwen3.5, nomic-embed-text | None found. Apache-2.0. |
| Connected services (MCP connectors) | Their own terms. Each connector is the client's account with that provider. See [Connectors](#connectors). |

## Python packages (runtime)

Direct dependencies (`pyproject.toml`):

| Package | Version | License | Used for |
|---|---|---|---|
| docling | 2.143.0 | MIT | PDF / image parsing, layout, OCR orchestration |
| fastapi | 0.162.0 | MIT | HTTP API |
| httpx | 0.28.1 | BSD-3-Clause | Assistant's calls to chat and embedding providers |
| uvicorn | 0.54.0 | BSD-3-Clause | ASGI server |
| pydantic-settings | 2.16.1 | MIT | `.env` / environment settings |
| python-multipart | 0.0.32 | Apache-2.0 | File uploads |
| onnxruntime | 1.31.1 | MIT | Runs the OCR models |
| openpyxl | 3.1.5 | MIT | Reading .xlsx files into the document library |
| numpy | 2.5.4 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | Page images |
| pillow | 13.0.0 | MIT-CMU | Image decoding |
| pypdfium2 | 5.14.0 | BSD-3-Clause, Apache-2.0 (PDFium) | PDF text layer, page rendering |
| pyyaml | 6.0.3 | MIT | Reading `config/model_config.yml` |
| registers | 7.5.0 | MIT | API-key store |
| sqlmodel | 0.0.48 | MIT | Database layer under `registers` |
| typing-extensions | 4.16.0 | PSF-2.0 | Typing back-ports |
| mcp | 2.3.0 | MIT | MCP client for connectors |
| cryptography | 50.0.2 | Apache-2.0 OR BSD-3-Clause | Fernet encryption of connector tokens |

Notable packages installed with the above:

| Package | Version | License |
|---|---|---|
| docling-core / docling-parse / docling-ibm-models | 2.104.0 / 7.23.1 / 4.0.4 | MIT |
| rapidocr | 3.10.0 | Apache-2.0 (code); bundled OCR models: see below |
| opencv-python-headless (with rapidocr) | 5.0.0.93 | Apache-2.0 (bundles third-party code, see its `LICENSE-3RD-PARTY.txt`) |
| torch / torchvision | 2.14.1 / 0.29.1 | Apache-2.0 AND BSD-2/3-Clause AND BSL-1.0 AND MIT (torch); BSD (torchvision) |
| transformers / huggingface-hub / safetensors | 5.21.0 / 1.33.0 / 0.8.0 | Apache-2.0 |
| scipy | 1.18.1 | BSD-3-Clause |
| starlette | 1.10.0 | BSD-3-Clause |
| et-xmlfile (with openpyxl) | 2.0.0 | MIT |
| pydantic | 2.14.1 | MIT |
| sqlalchemy | 2.1.6 | MIT |
| python-dotenv | 1.2.4 | BSD-3-Clause |

Development and test only (not needed to run the service): pytest 9.1.1 (MIT).

## Dashboard packages (`web/`)

Licenses from each package's `package.json`. Runtime: bundled into `web/dist`
by `npm run build`, which the API serves.

| Package | Version | License | Used for |
|---|---|---|---|
| react / react-dom (with scheduler 0.27.0) | 19.2.9 | MIT | UI |
| react-router (with cookie 1.1.1, set-cookie-parser 2.7.3) | 7.18.4 | MIT | Routing |
| @tanstack/react-query / @tanstack/query-core | 5.104.1 | MIT | Server state |
| openapi-fetch (with openapi-typescript-helpers 0.1.0) | 0.17.0 | MIT | Typed API client |
| lucide-react | 1.54.0 | ISC | Icons |
| @fontsource-variable/inter | 5.3.0 | OFL-1.1 (SIL Open Font License; Inter © The Inter Project Authors) | Inter font files. OFL allows bundling and redistribution with software; the font may not be sold on its own, and its license text (`node_modules/@fontsource-variable/inter/LICENSE`) goes with it |

Development only (not in `web/dist`): vite 7.3.7, @vitejs/plugin-react 5.2.0,
vitest 5.0.5, openapi-typescript 7.13.0, @testing-library/react 16.3.3,
@testing-library/dom 10.4.2, @testing-library/user-event 14.6.8, jsdom 30.1.3,
@types/react, @types/react-dom, @types/node (all MIT); typescript 5.9.3 and @playwright/test 1.63.0
(Apache-2.0).

## Model weights

| Model | Where it comes from | License | Notes |
|---|---|---|---|
| Docling layout model "heron" | Hugging Face `docling-project/docling-layout-heron`, downloaded on first start (or `main.py download-models`) | Apache-2.0 (model card) | |
| PP-OCRv6 small detection / recognition, `ch_ppocr_mobile_v2.0_cls` | Bundled in the `rapidocr` wheel | Apache-2.0; weights © Baidu / PaddleOCR rights holders | RapidOCR's `MODEL_LICENSES.md` lists the files and their SHA-256. Redistribution must keep the Apache-2.0 notices. The direction classifier is not used (`use_cls=False`). |
| Qwen3.5 4B (`qwen3.5:4b`) | Ollama library | Apache-2.0 (Alibaba Cloud / Qwen team) | The partner, the role assistants and the document assistant |
| nomic-embed-text v1.5 (`nomic-embed-text`) | Ollama library (publisher: Nomic AI) | Apache-2.0 (model card) | Document library search embeddings |

## Runtime services

### Ollama

Runs the models locally. MIT license (github.com/ollama/ollama). Model weights
pulled through Ollama keep their own licenses (above).

### Connectors

Connectors talk to the publisher's own MCP server (or, for the built-in workspace database, a local SQLite
file). Nothing of theirs is installed; their API terms, data use and retention, and the client's own
account and agreement with them apply. Some (for example n8n, under its Sustainable Use License) run on
software the client hosts under that software's own license.

### Cloud model providers (optional)

The assistant can be pointed at OpenAI, Anthropic or OpenRouter in
`config/model_config.yml`. No SDK is used, so nothing of theirs is installed;
their API terms (data use, retention, the client's own account and agreement
with them) apply instead. The shipped configuration uses local Ollama only.

## When you deliver the system

* Installing with `uv sync` on the client's machine downloads each package
  from PyPI under its own license. If you hand over a bundled environment,
  installer or container instead, you are redistributing those packages:
  include this file and the license texts that ship inside each package
  (`.venv/Lib/site-packages/<package>-<version>.dist-info/licenses/`), and
  keep Apache-2.0 `NOTICE` files.
* Delivering a built dashboard (`web/dist`) redistributes the npm runtime
  packages above. MIT, ISC and OFL-1.1 require their copyright and license
  text with copies: include this file and each runtime package's `LICENSE`
  (`web/node_modules/<package>/LICENSE`, `LICENSE.md` for react-router).
* Model weights are downloaded by the client's machine from Hugging Face and
  Ollama under the licenses above.

## Regenerate the package list

```bash
uv run python -m scripts.licenses
```

## Sources

* Qwen3.5-4B: https://llm-stats.com/models/qwen3.5-4b
* nomic-embed-text: https://ollama.com/library/nomic-embed-text · https://huggingface.co/nomic-ai/nomic-embed-text-v1.5
* Docling layout model card: https://huggingface.co/docling-project/docling-layout-heron
* RapidOCR model licenses: `MODEL_LICENSES.md` in the `rapidocr` package
