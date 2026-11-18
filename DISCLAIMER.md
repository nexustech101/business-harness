# Disclaimer and limitation of liability

This document applies to the Business Harness (the API, its knowledge index,
the business partner, the role assistants, the connectors and the dashboard)
and everything it produces (together, "the Software"). It is a template written
by the developer, not legal advice. Have an attorney licensed in your state
review it, and the contract it is attached to, before relying on it.

## 1. Not legal, tax, financial or accounting advice

The Software stores a business's documents and what the owner tells it, and
uses language models to answer questions, draft assistants, notes and
messages, and call connected services. It does not give legal, tax, financial
or accounting advice, and it does not make business decisions. The partner's
and the assistants' answers and drafts are suggestions for the business's
people to check. The assistants answer from passages they retrieve; they can
miss a document, cite the wrong one, or misstate what a passage says.

## 2. Every output must be checked by a person

All output is produced automatically by software and machine-learning models
and **can be wrong or incomplete**. In particular:

* text read by OCR from scans and photos can contain misread characters,
  digits and punctuation;
* layouts and documents the Software was not built or tested for may be
  partly read;
* a model can misunderstand a question, invent facts not in the documents,
  or call a connector with the wrong arguments;
* a value may be correct as stored while the source document itself is wrong.

Before an answer, draft or action is relied on, sent to anyone or used in a
filing, a person responsible for it must check it against the source.

## 3. No warranty

THE SOFTWARE IS PROVIDED "AS IS" AND "AS AVAILABLE", WITHOUT WARRANTY OF ANY
KIND, EXPRESS OR IMPLIED, INCLUDING WARRANTIES OF MERCHANTABILITY, FITNESS FOR
A PARTICULAR PURPOSE, ACCURACY, AND NON-INFRINGEMENT. No statement of accuracy
in the documentation (including test results) is a warranty about the
client's documents or data.

## 4. Limitation of liability

TO THE MAXIMUM EXTENT PERMITTED BY LAW, THE DEVELOPER IS NOT LIABLE FOR ANY
INDIRECT, INCIDENTAL, SPECIAL, CONSEQUENTIAL OR PUNITIVE DAMAGES, OR FOR LOST
PROFITS, LOST DATA, TAXES, PENALTIES OR INTEREST, ARISING FROM USE OF OR
RELIANCE ON THE SOFTWARE OR ITS OUTPUT, INCLUDING ACTIONS TAKEN THROUGH
CONNECTED SERVICES, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGES. THE
DEVELOPER'S TOTAL LIABILITY FOR ANY CLAIM IS LIMITED TO THE FEES PAID FOR THE
SOFTWARE OR SERVICE GIVING RISE TO THE CLAIM IN THE TWELVE MONTHS BEFORE THE
CLAIM.

## 5. The client's responsibilities

The Software runs on systems the client controls. The client is responsible for:

* checking all output before use (section 2);
* the write policy of each role assistant (`auto`, `ask`, `deny`) and every
  approval it grants: a write set to `auto` runs without a person seeing it;
* the security of the machines, networks, backups and accounts it runs on,
  including the API keys, the secrets key that encrypts connector tokens
  (`BUSINESS_SECRETS_KEY` or `data/secrets.key`) and the accounts connectors
  sign in to;
* its obligations as a holder of personal, customer and employee data under
  the laws that apply to it;
* how long documents, workspace records and databases are kept, and their
  deletion, including the library and business databases, the stored original
  files, the workspace databases and their backups;
* obtaining any consent its documents and data require before they are processed;
* the terms of the services it connects (their API terms, data use and
  retention) and the licenses of third-party components it runs, including
  model weights (see `THIRD_PARTY_LICENSES.md`).

## 6. Data handling, as designed

* The API-key database stores only hashed keys and their metadata. Logs carry
  request ids, timings and counts, not document text.
* Documents added to the library (`/v1/library/documents`) are stored for
  search. The original file is kept on disk (`library.files` in
  `config/model_config.yml`, default `data/files/`) so its pages can be shown
  and downloaded. The library database (`library.database`) holds the
  searchable text, in which Social Security numbers are masked to the last
  four digits; names, addresses and amounts are stored as printed. Each API key
  sees only the documents it added; admin keys see all of them. Documents and
  (once no other document uses it) the original file stay until deleted
  through the API.
* The business database (`business.database`) holds each workspace's profile,
  interview answers, assistants, approvals, notes and installed connectors.
  Connector tokens are encrypted with the secrets key. Workspace databases are
  SQLite files next to it, deleted with their connector.
* Approval decisions are recorded with the name of the API key that made them
  and the time. They record who approved an action in the Software; they do
  not replace the client's own records.
* Models run locally through Ollama by default; documents are not sent to an
  outside AI service unless the client configures `config/model_config.yml` to
  use one. With a cloud provider, that provider receives the questions asked
  and the results of the tools: passages of documents and workspace records
  (Social Security numbers masked), connector results and database rows.
* Connectors send what an assistant passes them to the connected service.

These are properties of the Software as delivered. Changes to its
configuration or code by anyone other than the developer can change them.

## 7. Third-party software, services and models

The Software depends on third-party packages, services, connectors and model
weights that are provided by others under their own licenses and terms and
without warranty from the developer. Their availability, licensing and
behaviour may change.
