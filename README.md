# MarketPilot

Multi-tenant marketing workspace for agencies: clients, brand profiles, a per-client knowledge
base (hybrid RAG), and AI strategy generation on **your own model** (bring your own key).
Requirements live in [`srs/`](srs/Software%20Requirements%20Specification.md); design specs and
plans in [`docs/`](docs/superpowers).

## Quick start

Prerequisites: Docker, [uv](https://docs.astral.sh/uv/) (Python 3.10), Node 22 and pnpm 10.

```bash
cp .env.example .env            # then set JWT_SECRET and FERNET_KEYS (command is in the file)
docker compose up -d postgres redis

cd apps/api
uv sync --all-groups
uv run alembic upgrade head
uv run uvicorn app.main:app --port 8000                          # API
uv run celery -A app.jobs.celery_app worker --pool=solo -l info  # document indexing worker

cd ../web
pnpm install
pnpm dev                                                         # http://localhost:3000
```

## Tests

```bash
cd apps/api && uv run ruff check . && uv run mypy app && uv run pytest -q
cd apps/web && pnpm lint && pnpm test      # on a small machine: pnpm exec vitest run --maxWorkers=2
cd apps/web && pnpm build && pnpm start    # then, with the API and worker running: pnpm e2e
```

## Retrieval quality (golden questions)

`apps/api/rag_eval/` holds a small fixed corpus (8 documents for a fictional coffee roaster) and 18
golden questions, many of them paraphrased so keyword overlap alone does not answer them. The
script indexes the corpus for a throwaway tenant, runs each question through the real hybrid
retrieval (pgvector + full-text, reciprocal rank fusion) and reports **hit rate at k**: the share
of questions whose expected document is among the top k chunks. The tenant is deleted afterwards.

```bash
cd apps/api
uv run python -m rag_eval.run                      # hit@1, hit@3, hit@5 plus every miss
uv run python -m rag_eval.run --k 3 8 --min 0.85   # exit code 1 if hit@8 < 85%
```

It needs Postgres and `.env` like the API, but no worker or LLM key. To extend it, add a `.md`
file to `rag_eval/corpus/` and questions to `rag_eval/golden_questions.json` (`expected` is the
file name). Baseline with `BAAI/bge-small-en-v1.5` embeddings: hit@1 83%, hit@3 100%, hit@5 100%.
`tests/test_rag_eval.py` fails if hit@3 drops below 90%, so a retrieval regression shows up in CI.

## Bring your own model

Open **Settings → AI models**, add a connection (OpenAI, Anthropic, Ollama or any
OpenAI-compatible base URL), press **Test** to list its models, then choose a connection and model
per task (`strategy`, `content`, `analysis`). API keys are encrypted at rest and write-only in the
UI. The monthly budget is on the same page, and per-call cost and tokens are on **Usage**.

### Local models (Ollama)

Model calls are made by the **API server**, not by your browser. So the URL you give an Ollama
connection must be reachable *from the machine the API runs on*. `http://localhost:11434` on your
laptop is not reachable from a cloud-hosted API.

Pick one of two setups:

**A. Run the API locally (simplest).** Start Ollama (`ollama serve`, default
`http://localhost:11434`), pull a model (`ollama pull llama3.1`), run the API as in the quick start
and add an Ollama connection with Base URL `http://localhost:11434`. If the API itself runs in a
container, use `http://host.docker.internal:11434` instead.

**B. Use a cloud-hosted API with a tunnel.** Expose Ollama through a tunnel and use the public URL
as the Base URL:

```bash
# Cloudflare Tunnel
cloudflared tunnel --url http://localhost:11434
# or ngrok (Ollama checks the Host header)
ngrok http 11434 --host-header="localhost:11434"
```

Paste the printed `https://…` address into **Base URL**. Ollama has no authentication of its own, so
anyone who has the tunnel URL can use your model. Treat the URL as a secret, put the tunnel behind
access control where your provider supports it, and stop it when you are done. Quick tunnel URLs
change on every restart, so update the connection when that happens.

Notes:

- No API key is needed for Ollama; the key field is hidden for that provider.
- **Test** calls `GET {base}/api/tags`; if it fails, the error is shown on the connection.
- Structured output (strategy JSON) uses Ollama's native `format` schema, so pick a model that
  follows JSON instructions reliably. Small models may fail schema validation more often.
- Local models cost nothing: Ollama calls are recorded at $0.00, so they appear in the usage
  dashboard (tokens and latency) but add nothing to the monthly budget.
