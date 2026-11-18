# Software Requirements Specification

**AI Digital Marketing Head: Multi-Tenant SaaS Platform** (working name: *MarketPilot*)

Version 1.0 | 18 November 2026 | Prepared by: \[Team / Author name\] | Source: AI Digital Marketing Head - SaaS Platform Challenge

## 1. Introduction

### 1.1 Purpose

This document specifies the requirements, architecture, technology stack, project structure and data models for an AI-powered, multi-tenant SaaS platform that acts as an AI Digital Marketing Head for agencies. It is the single source of truth for building, demoing and documenting the product, and it covers every requirement in the hackathon problem statement.

### 1.2 Scope

MarketPilot lets agencies manage multiple clients in isolated workspaces, audit websites and social accounts automatically, generate AI marketing strategies with prioritized tasks and a 30-day content calendar, create on-brand content, track team work, and export client-ready reports. Users connect their own AI models (BYOM), so the platform carries no AI inference cost.

| # | Feature in the problem statement | Class | SRS section |
| --- | --- | --- | --- |
| 1 | Multi-tenant SaaS platform (auth, agency/client management, RBAC, isolation) | P0 | FR-AUTH, FR-TEN |
| 2 | Automated audit engine (SEO, social, competitors, GA, Search Console) | P0 | FR-AUD |
| 3 | AI strategy generator (tasks, 30-day calendar, RAG) | P0 | FR-STR, FR-RAG |
| 4 | BYOM integration (OpenAI, Anthropic, local; per-task model; usage and cost) | P0 | FR-BYOM |
| 5 | Content generation (blog, social, SEO, brand voice, A/B variations) | P0 | FR-CON |
| 6 | Team collaboration (Kanban, performance analytics, real-time) | P1 | FR-COL |
| 7 | Automated reporting (PDF, month-over-month charts, white-label) | P1 | FR-REP |
| 8 | Integrations (Facebook, Instagram, LinkedIn, WordPress, Asana, Trello) | P1 | FR-INT |

### 1.3 Priority legend

- **P0**: Core MVP. Maps to the statement's Must Have list. All P0 requirements ship.
- **P1**: Bonus. Maps to the statement's Advanced Features list. All P1 requirements are targeted and built after P0 is complete.
- **P2**: Stretch. Built only if time remains.

### 1.4 Definitions

| Term | Meaning |
| --- | --- |
| Tenant | An agency account. The unit of data isolation. |
| Client | A business the agency serves. Belongs to exactly one tenant. |
| BYOM | Bring Your Own Model. Tenants register their own AI provider keys or local endpoints. |
| RAG | Retrieval Augmented Generation. Prompts are grounded with retrieved client context. |
| RLS | PostgreSQL Row Level Security. |
| Job | A long-running background task executed by Celery (audit, strategy, report, indexing). |
| Brand profile | A client's voice, tone, audience and do/don't rules used in every generation. |

### 1.5 Design decision log

| ID | Decision | Reason |
| --- | --- | --- |
| D-01 | Self-built JWT authentication (access plus rotating refresh tokens) | Listed in the statement; full control of tenant and role claims |
| D-02 | pgvector inside the main PostgreSQL | One datastore; tenant isolation reuses the same RLS policies |
| D-03 | Modular monolith (FastAPI) plus a Celery worker | Allowed by the statement; simplest scalable shape for a small team |
| D-04 | Vercel (frontend), Render (API and worker), Neon (Postgres), Render Key Value or Upstash (Redis) | $0 hosting for the live demo |
| D-05 | Social analytics via CSV/JSON export import (P0); live platform OAuth is P2 | Facebook, Instagram and LinkedIn APIs need app review, which blocks a free demo |
| D-06 | Embeddings via fastembed (ONNX, 384 dimensions, BAAI/bge-small-en-v1.5) | Runs inside a 512 MB container without PyTorch |
| D-07 | No LangChain; a thin in-house provider router and RAG pipeline | Fewer dependency conflicts; the BYOM router is the showcase piece |
| D-08 | SSE for job progress; WebSocket for Kanban collaboration | Matches each traffic pattern; both meet the real-time requirement |
| D-09 | API and Celery worker run in one Render Docker service (supervisord) | Render has no free background worker |
| D-10 | Google OAuth app in Testing mode for GA4 and Search Console | Free; sensitive scopes otherwise require verification (see risks) |

## 2. Overall Description

### 2.1 Product perspective

MarketPilot replaces the 15+ tool workflow described in the statement with one platform. It is a web application (responsive, mobile-friendly) backed by a REST and real-time API, a background job system, and a tenant-isolated PostgreSQL database.

### 2.2 User roles and permissions

Roles are scoped to a tenant through a membership record. A person may belong to more than one agency and switches the active tenant, which re-issues the JWT.

| Role | Description |
| --- | --- |
| Admin | Agency owner. Full control of the tenant, members, billing-style settings and AI connections. |
| Manager | Runs clients and projects. Creates audits, strategies, reports and assigns work. |
| Team Member | Executes tasks and produces content. Read access to client data they are assigned to. |

| Capability | Admin | Manager | Member |
| --- | --- | --- | --- |
| Manage agency settings, members, roles, white-label branding | Yes | No | No |
| Create and edit clients, brand profiles, knowledge documents | Yes | Yes | No |
| Manage AI connections (BYOM) and per-task model routing | Yes | Yes | No |
| View usage and cost analytics | Yes | Yes | No |
| Connect Google, WordPress, Trello, Asana | Yes | Yes | No |
| Run audits, generate strategies, generate reports | Yes | Yes | No |
| View audits, strategies, reports | Yes | Yes | Yes |
| Generate content and variations | Yes | Yes | Yes |
| Approve and publish content | Yes | Yes | No |
| Create tasks and move own tasks on Kanban | Yes | Yes | Yes |
| Assign tasks to others | Yes | Yes | No |
| Team performance analytics | All | All | Own only |

### 2.3 Operating environment

- Browsers: current Chrome, Edge, Firefox, Safari; mobile browsers down to 360 px width.
- Server: Linux containers (Docker), Python 3.12 runtime.
- Local development: Docker Compose with Postgres, Redis, API, worker and web.

### 2.4 Constraints

- Total running cost for the demo must be $0. All services use free tiers.
- Hackathon rules: public GitHub repository, original code, live demo with sample data, 10-minute pitch, architecture and setup documentation.
- The statement's suggestion lists are not hard requirements, but deviations (pgvector, Render/Vercel, Celery/Redis) are justified in the architecture document.

### 2.5 External dependencies

| Service | Use | Cost and caveat |
| --- | --- | --- |
| Google PageSpeed Insights API v5 | Page speed and mobile checks | Free; API key; rate limited |
| Google Analytics Data API (GA4) | Traffic and conversion metrics | Free; OAuth |
| Google Search Console API | Queries, clicks, indexing | Free; OAuth |
| OpenAI, Anthropic APIs | BYOM cloud models | Paid by the user with their own key |
| Ollama (local) | BYOM local models | Free; user supplied endpoint |
| WordPress REST API | Publish content | Free; application passwords |
| Trello and Asana REST APIs | Task sync | Free tiers |
| Facebook, Instagram, LinkedIn | Social analytics | CSV/JSON import in MVP; OAuth is P2 |

## 3. System Architecture

### 3.1 Architectural style

A **modular monolith** API (FastAPI) with clearly separated domain modules, plus a **Celery worker** for long-running jobs. Modules communicate through service interfaces and an internal event bus, so any module can later be extracted into a service. The frontend is a separate Next.js application.

### 3.2 System context

```
 Agency users (Admin / Manager / Member)       Client sites and competitor sites
        │ HTTPS                                         ▲ HTTP crawl
        ▼                                               │
 ┌───────────────┐   REST + SSE + WebSocket   ┌─────────────────────────────┐
 │  Next.js Web  │◀──────────────────────────▶│  FastAPI API + Celery Worker │──▶ Google: PageSpeed, GA4, GSC
 │   (Vercel)    │                            │          (Render)            │──▶ OpenAI / Anthropic / Ollama
 └───────────────┘                            └───────┬──────────────┬──────┘──▶ WordPress / Trello / Asana
                                                      │              │
                                         PostgreSQL 16 + pgvector   Redis 7
                                                (Neon)          (broker, cache, pub/sub)
```

### 3.3 Logical architecture

```
┌──────────────────────────── Presentation (Next.js 16, React 19) ─────────────────────────────┐
│ Auth · Dashboard · Clients · Audits · Strategy · Content · Kanban · Reports · AI Settings    │
└───────────────────────────────────────────┬──────────────────────────────────────────────────┘
                                            │ REST (OpenAPI) · SSE · WebSocket
┌───────────────────────────────────────────▼──────────────────────────────────────────────────┐
│ API layer (FastAPI): routers · JWT middleware · tenant context · RBAC dependencies · schemas   │
├───────────────────────────────────────────────────────────────────────────────────────────────┤
│ Domain modules: auth · tenants · clients · audits · strategy · content · ai_gateway · rag     │
│                 tasks · reports · integrations · usage · notifications                        │
├───────────────────────────────────────────────────────────────────────────────────────────────┤
│ Infrastructure: SQLAlchemy repos · Redis · Celery tasks · HTTP clients · crypto · storage     │
└───────────────┬──────────────────────────────┬──────────────────────────────┬─────────────────┘
                │                              │                              │
        PostgreSQL + pgvector                Redis                      External APIs
```

### 3.4 Multi-tenancy and isolation

```
 Request ──▶ JWT verify ──▶ claims: sub, tenant_id, role ──▶ RBAC check (role vs endpoint)
                                         │
                                         ▼
                    DB session opens a transaction and runs:
                    SELECT set_config('app.tenant_id', '<tenant_id>', true)
                                         │
                                         ▼
   Every tenant table has tenant_id + RLS policy:  tenant_id = current_setting('app.tenant_id')::uuid
                                         │
        Vector search, jobs, files and cache keys are all scoped by the same tenant_id
```

Isolation is enforced in four layers: JWT claims, application RBAC, PostgreSQL RLS (defence in depth, so a missed filter cannot leak data), and tenant-prefixed cache and storage keys. The application connects as a non-owner role with `FORCE ROW LEVEL SECURITY` on all tenant tables.

### 3.5 Asynchronous job flow

```
 Web ──POST /audits──▶ API ──insert job row (queued)──▶ Postgres
                        │ enqueue task (tenant_id, job_id)
                        ▼
                      Redis (broker) ──▶ Celery worker ──▶ runs crawler / LLM / PDF
                                              │ publishes progress events
                                              ▼
                                        Redis pub/sub ──▶ API SSE endpoint ──▶ Web progress bar
                                              │ on finish
                                              ▼
                                    results saved, job row = succeeded, notification created
```

Jobs have statuses `queued`, `running`, `succeeded`, `failed`, `cancelled`, are idempotent per `job_id`, retry with exponential backoff, and always carry the `tenant_id` so the worker sets the same RLS context as the API. Application code uses a task layer (`app/jobs`), so the queue backend can be replaced without touching domain code.

### 3.6 RAG pipeline

```
 Ingest:   documents / brand voice / past audits / published content
              │ extract text → chunk (≈500 tokens, 80 overlap) → embed (fastembed, 384-d)
              ▼
           document_chunks (pgvector, HNSW index, tenant_id + client_id)

 Generate: task request (e.g. monthly strategy for client X)
              │ build query from goals + audit findings
              ▼
           similarity search WHERE tenant_id AND client_id  → top-k chunks (k=8)
              │ rerank by recency and source type, trim to token budget
              ▼
           prompt = system rules + brand profile + audit summary + retrieved chunks + schema
              │
              ▼
           AI Gateway (selected model) → JSON validated against Pydantic schema → saved with citations
```

Every generated strategy and content piece stores the chunk IDs it used, so the UI can show *sources used*.

### 3.7 BYOM AI gateway

```
 Strategy / Content / Analysis services
              │  gateway.complete(task='strategy', client_id, messages, schema)
              ▼
 ┌────────────────────────── AI Gateway ──────────────────────────┐
 │ 1. resolve route: tenant task settings → connection + model    │
 │ 2. decrypt key (Fernet) in memory only                         │
 │ 3. provider adapter: OpenAI | Anthropic | Ollama (OpenAI-style)│
 │ 4. retry, timeout, structured-output validation                │
 │ 5. record usage: tokens in/out, latency, estimated cost        │
 └────────────────────────────────────────────────────────────────┘
```

The adapter interface is `ProviderAdapter.complete()`, `.stream()` and `.embed()`. Adding a provider means adding one adapter class. Cost is estimated from a pricing table (per million tokens) stored in the database; local models are priced at zero.

### 3.8 Deployment architecture

```
 GitHub (public repo) ──Actions CI──▶ lint, type-check, tests, build
      │ push to main
      ├──▶ Vercel: Next.js web (HTTPS, free hobby plan)
      └──▶ Render: Docker web service  [ uvicorn API  +  celery worker --pool=solo ]  (supervisord)
                          │                                  │
                          ▼                                  ▼
                Neon PostgreSQL 16 + pgvector      Render Key Value / Upstash (Redis)
```

The local stack uses Docker Compose with the same images, so local and production behave the same.

## 4. Technology Stack and Versions

### 4.1 Pinned versions

Versions are compatible-release ranges chosen from one coherent matrix. Exact versions are frozen in lock files at project bootstrap (4.3). Check each range against the registries on the day you scaffold.

**Runtime and tooling**

| Component | Version | Notes |
| --- | --- | --- |
| Node.js | 22.x LTS | Satisfies Next.js 16 minimum (20.9+) |
| pnpm | 10.x | Via Corepack |
| TypeScript | 5.x (5.6 or newer) | Next.js 16 requires 5.1+ |
| Python | 3.12.x | Single version for API, worker and tests |
| uv (Python package manager) | 0.5 or newer | Generates `uv.lock` |
| Docker Engine and Compose | 27+ and v2 | Local stack and Render image |

**Frontend**

| Component | Version | Notes |
| --- | --- | --- |
| Next.js (App Router) | 16.x | Turbopack default; deploys on Vercel |
| React and React DOM | 19.x (same minor for both) | Required by Next.js 16 App Router |
| @types/react, @types/react-dom | 19.x | Must match React major |
| Tailwind CSS | 4.x with @tailwindcss/postcss | CSS-first config |
| shadcn/ui (CLI-generated components) | current CLI, Tailwind 4 and React 19 template | Components are copied into the repo |
| Radix UI primitives | version pulled by shadcn CLI | Do not mix manual versions |
| TanStack Query | 5.x | Server state |
| Zustand | 5.x | Client state |
| React Hook Form, Zod, @hookform/resolvers | 7.x, 4.x, 5.x | Resolver 5 supports Zod 4 |
| Recharts | 3.x | Supports React 19 |
| @dnd-kit/core, @dnd-kit/sortable | 6.x, 10.x | Kanban |
| Vitest, Testing Library, Playwright | 3.x, 16.x, 1.x | Unit, component, end-to-end |
| ESLint and Prettier | 9.x and 3.x | Flat config |

**Backend**

| Component | Version | Notes |
| --- | --- | --- |
| FastAPI | >=0.115, <1.0 | Requires Pydantic 2 |
| Pydantic and pydantic-settings | 2.x | Do not use v1 |
| Uvicorn (standard extras) | >=0.30 | ASGI server |
| SQLAlchemy | 2.0.x (async API) | With asyncpg for the API |
| asyncpg | >=0.29 | Async driver |
| psycopg (binary) | 3.2.x | Sync driver for Celery tasks and Alembic |
| Alembic | >=1.13 | Migrations |
| pgvector (Python) | >=0.3 | SQLAlchemy and psycopg support |
| Celery | 5.5.x | Python 3.12 supported |
| redis-py | >=5.0, <6 | Matches Celery 5.5 and kombu |
| PyJWT | 2.x | HS256 or RS256 |
| argon2-cffi | >=23 | Password hashing |
| cryptography | >=43 | Fernet encryption of API keys |
| sse-starlette | 2.x | Server-Sent Events |
| httpx | >=0.27 | Async HTTP and provider calls |
| beautifulsoup4 and lxml | 4.12.x and 5.x | HTML parsing for the crawler |
| openai SDK | 1.x or newer | Also used for Ollama's OpenAI-compatible endpoint |
| anthropic SDK | >=0.40 | Claude models |
| fastembed | >=0.4 | ONNX embeddings, 384-d |
| google-api-python-client, google-auth-oauthlib | 2.x, 1.x | GA4, Search Console, PageSpeed |
| WeasyPrint | >=62 | PDF; needs Pango (present in Debian bookworm) |
| Jinja2 and matplotlib | 3.1.x and 3.9+ | Report templates and server-side charts |
| pytest, pytest-asyncio, ruff, mypy | 8.x, 0.24+, current, 1.x | Quality gates |

**Data and infrastructure**

| Component | Version | Notes |
| --- | --- | --- |
| PostgreSQL | 16 | Supported by Neon and by the pgvector/pgvector:pg16 local image |
| pgvector extension | 0.8.x | HNSW index support |
| Redis protocol | 7.x | Local: redis:7-alpine. Production: Render Key Value or Upstash (Redis-compatible) |
| Base image | python:3.12-slim-bookworm | API and worker |
| supervisord | 4.2.x | Runs API and worker in one container |

### 4.2 Compatibility rules (no version mismatch)

1. One Python (3.12) and one Node (22 LTS) everywhere: local, CI, Docker and Vercel (`engines` and `.nvmrc` set).
2. React 19 with Next.js 16 and `@types/react` 19; never mix React 18 libraries. Check that each UI package declares React 19 support before adding it.
3. Tailwind 4 with the shadcn template generated for Tailwind 4; do not add a `tailwind.config.js` from v3 tutorials.
4. FastAPI requires Pydantic 2; SQLAlchemy 2.0 async with asyncpg; Celery tasks use the sync psycopg 3 engine because Celery workers are synchronous.
5. Celery 5.5 with redis-py below 6; the worker runs with `--pool=solo` on the free tier and `prefork` elsewhere.
6. Embedding dimension is fixed at 384 in the schema; changing the embedding model requires a migration and re-indexing.
7. Database and Redis versions are identical in Compose, CI service containers and production.

### 4.3 Version freeze procedure

- Backend: `uv add <packages>`, then commit `pyproject.toml` and `uv.lock`; Docker and CI install with `uv sync --frozen`.
- Frontend: commit `pnpm-lock.yaml`; CI uses `pnpm install --frozen-lockfile`.
- Renovate or Dependabot opens grouped update PRs; CI must pass before merge.

## 5. Project Structure

A single public monorepo.

```
marketpilot/
├── README.md                      setup, architecture summary, demo credentials
├── docs/
│   ├── SRS.md  ARCHITECTURE.md  API.md  DEPLOYMENT.md  DECISIONS.md
│   └── diagrams/
├── docker-compose.yml             postgres(pgvector) · redis · api · worker · web
├── .github/workflows/ci.yml       lint · type-check · test · build · migrate check
├── .env.example
├── apps/
│   ├── web/                       Next.js 16 frontend
│   │   ├── app/
│   │   │   ├── (auth)/login  register  accept-invite
│   │   │   ├── (app)/dashboard
│   │   │   ├── (app)/clients/[clientId]/{overview,audits,strategy,content,calendar,reports}
│   │   │   ├── (app)/tasks            Kanban board
│   │   │   ├── (app)/team             performance analytics
│   │   │   ├── (app)/settings/{agency,members,ai-models,integrations,usage,branding}
│   │   │   └── share/report/[token]   public white-label report view
│   │   ├── components/{ui,layout,charts,kanban,audit,strategy,content}
│   │   ├── lib/{api-client.ts,auth.ts,sse.ts,ws.ts,schemas/}
│   │   ├── hooks/  stores/  tests/
│   │   └── package.json  next.config.ts  postcss.config.mjs
│   └── api/                       FastAPI backend
│       ├── app/
│       │   ├── main.py  config.py  deps.py
│       │   ├── core/{security.py,tenancy.py,rbac.py,crypto.py,errors.py,logging.py}
│       │   ├── db/{session.py,base.py,models/,rls.sql}
│       │   ├── modules/
│       │   │   ├── auth/  tenants/  clients/
│       │   │   ├── audits/{crawler,seo_checks,pagespeed,social,competitors,google}
│       │   │   ├── strategy/{generator,prompts,calendar,task_planner}
│       │   │   ├── content/{generator,seo,variations,brand_voice}
│       │   │   ├── ai_gateway/{router,usage,pricing,providers/{openai,anthropic,ollama}}
│       │   │   ├── rag/{ingest,chunking,embeddings,retrieval}
│       │   │   ├── tasks/{kanban,realtime,analytics}
│       │   │   ├── reports/{builder,charts,templates,pdf}
│       │   │   ├── integrations/{wordpress,trello,asana,social_import}
│       │   │   └── notifications/
│       │   ├── jobs/{celery_app.py,progress.py,tasks_*.py}
│       │   └── api/v1/*.py                  routers
│       ├── alembic/  migrations/
│       ├── tests/{unit,integration,isolation}
│       ├── seed/{seed_demo.py,sample_data/}
│       ├── Dockerfile  supervisord.conf  pyproject.toml  uv.lock
└── scripts/{dev.sh,migrate.sh,reset-demo.sh}
```

The `tests/isolation` suite proves tenant isolation: it creates two tenants and asserts that no endpoint, vector query or job can read the other tenant's rows.

## 6. User and Data Models

### 6.1 Entity relationship overview

```
tenants 1─* memberships *─1 users
tenants 1─* clients 1─* brand_profiles
tenants 1─* ai_connections 1─* task_model_routes
tenants 1─* usage_logs                       clients 1─* documents 1─* document_chunks (vector)
clients 1─* audits 1─* audit_findings        clients 1─* competitors
clients 1─* social_accounts 1─* social_metrics
clients 1─* strategies 1─* strategy_tasks    strategies 1─* calendar_items 1─* content_pieces 1─* content_variations
tenants 1─* tasks (Kanban) 1─* task_comments
clients 1─* reports        tenants 1─* integrations        tenants 1─* jobs        tenants 1─* audit_log
```

### 6.2 Core tables

All tenant tables include `id uuid`, `tenant_id uuid`, `created_at`, `updated_at`. Foreign keys are indexed.

| Table | Key columns | Purpose |
| --- | --- | --- |
| tenants | name, slug, plan, branding (logo\_url, primary\_color, report\_footer) | Agency account and white-label settings |
| users | email (unique), password\_hash, full\_name, is\_active | Global identity (not tenant scoped) |
| memberships | user\_id, tenant\_id, role (admin, manager, member), status, invited\_by | Role per tenant |
| refresh\_tokens | user\_id, tenant\_id, token\_hash, expires\_at, revoked\_at, replaced\_by | Rotating refresh tokens |
| clients | name, website\_url, industry, goals (jsonb), status | Client managed by the agency |
| brand\_profiles | client\_id, voice, tone, audience, keywords, do\_rules, dont\_rules, sample\_text | Brand voice consistency |
| ai\_connections | provider (openai, anthropic, ollama, openai\_compatible), label, base\_url, api\_key\_enc, key\_last4, is\_active | BYOM credentials, encrypted |
| task\_model\_routes | task\_type (strategy, content, analysis, embedding\_summary), connection\_id, model, temperature, max\_tokens | Model per task |
| usage\_logs | connection\_id, task\_type, client\_id, model, tokens\_in, tokens\_out, cost\_usd, latency\_ms, created\_by | Usage tracking and cost estimates |
| model\_pricing | provider, model, input\_per\_mtok, output\_per\_mtok | Cost estimation table (global, seeded) |
| audits | client\_id, type (website, social, competitor), status, score, summary, started\_at, finished\_at, raw (jsonb) | Audit runs |
| audit\_findings | audit\_id, category, severity, title, detail, url, recommendation, metric (jsonb) | Individual issues and insights |
| competitors | client\_id, name, url, notes, last\_snapshot (jsonb) | Competitor research targets |
| social\_accounts | client\_id, platform, handle, source (csv, api) | Social profiles |
| social\_metrics | social\_account\_id, period\_date, followers, reach, impressions, engagement, posts, extra (jsonb) | Imported performance data |
| strategies | client\_id, month, status, summary, goals, model\_used, sources (chunk ids) | Monthly strategy |
| strategy\_tasks | strategy\_id, title, description, priority (p1 to p4), effort\_hours, due\_date, task\_id | Generated actions, linked to Kanban |
| calendar\_items | strategy\_id, publish\_date, channel, topic, format, status | 30-day content calendar |
| content\_pieces | client\_id, calendar\_item\_id, type (blog, social), title, status, seo\_score, published\_url | Content unit |
| content\_variations | content\_piece\_id, label (A, B, C), body, meta (jsonb), is\_selected | A/B variations |
| documents | client\_id, source\_type (brand\_doc, past\_content, audit, upload), title, content\_hash, status | RAG sources |
| document\_chunks | document\_id, client\_id, chunk\_index, text, embedding vector(384) | RAG index with HNSW cosine index |
| tasks | client\_id, strategy\_task\_id, title, status (todo, doing, review, done), priority, assignee\_id, position, due\_date, completed\_at | Kanban cards |
| task\_comments | task\_id, author\_id, body | Collaboration |
| reports | client\_id, period\_start, period\_end, status, pdf\_path, share\_token, data (jsonb) | Generated reports |
| integrations | provider (google, wordpress, trello, asana), config\_enc, status, scopes | Third-party connections, encrypted |
| jobs | type, status, progress, payload, result\_ref, error, created\_by | Background job tracking |
| notifications | user\_id, type, body, read\_at | In-app alerts |
| audit\_log | actor\_id, action, entity, entity\_id, metadata, ip | Security audit trail |

### 6.3 JWT claims

| Token | Lifetime | Claims |
| --- | --- | --- |
| Access | 15 minutes | `sub` (user id), `tenant_id`, `role`, `jti`, `iat`, `exp` |
| Refresh | 7 days, rotated on use, reuse detection revokes the chain | `sub`, `tenant_id`, `jti`, hashed in the database |

### 6.4 RLS pattern

```sql
ALTER TABLE clients ENABLE ROW LEVEL SECURITY;
ALTER TABLE clients FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON clients
  USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
```

The same policy is generated for every table that has `tenant_id` by a migration helper. `users` and `model_pricing` are global and are never exposed through tenant-scoped queries.

## 7. Functional Requirements

Each requirement has an ID, a priority (section 1.3) and is testable.

### 7.1 Authentication (FR-AUTH)

| ID | Requirement | Pri |
| --- | --- | --- |
| FR-AUTH-01 | A visitor can register an agency with email and password. This creates the tenant and its first Admin. | P0 |
| FR-AUTH-02 | Login returns a 15-minute access token and a 7-day refresh token. Refresh tokens rotate on every use; reuse of an old token revokes the whole chain. Logout revokes the current refresh token. | P0 |
| FR-AUTH-03 | Passwords are hashed with Argon2id, minimum 10 characters. Login is rate limited (5 attempts per minute per IP and email) with temporary lockout. | P0 |
| FR-AUTH-04 | Admins invite members by email with a role. The invitation link is also shown in the UI for copying, so the system works without an email provider. | P0 |
| FR-AUTH-05 | A user with several memberships can switch the active agency; the server issues a new token pair for that tenant. | P0 |
| FR-AUTH-06 | Password reset through an emailed single-use token (SMTP provider with a free tier; console output in development). | P1 |

### 7.2 Tenants, clients and RBAC (FR-TEN)

| ID | Requirement | Pri |
| --- | --- | --- |
| FR-TEN-01 | Admins list members, change roles, deactivate members. The last Admin cannot be removed or demoted. | P0 |
| FR-TEN-02 | Create, edit, archive and list clients (name, website URL, industry, goals). | P0 |
| FR-TEN-03 | Each client has a brand profile: voice, tone, audience, keywords, do and don't rules, sample text. | P0 |
| FR-TEN-04 | Every endpoint enforces the permission matrix in section 2.2 on the server. UI hiding is cosmetic only. | P0 |
| FR-TEN-05 | Data isolation uses RLS (section 6.4). The isolation test suite must pass in CI before any merge. | P0 |
| FR-TEN-06 | Security-relevant actions (login, role change, key added, export, delete) are written to `audit_log`. | P0 |
| FR-TEN-07 | Admins set white-label branding: logo, primary color, report footer, agency display name. | P1 |

### 7.3 Automated audit engine (FR-AUD)

**Website technical SEO**

| ID | Requirement | Pri |
| --- | --- | --- |
| FR-AUD-01 | Crawl a client site (default 100 pages, depth 3, same origin). The crawler respects robots.txt, limits to 1 request per second per host, uses a 10 second timeout, and runs as a Celery job with live progress. | P0 |
| FR-AUD-02 | Detect broken links (internal and external: 4xx, 5xx, timeouts), redirect chains and redirect loops. | P0 |
| FR-AUD-03 | On-page checks: title and meta description presence and length, H1 count, canonical tag, missing image alt text, duplicate titles, Open Graph tags, structured data, HTTPS, sitemap.xml and robots.txt presence. | P0 |
| FR-AUD-04 | Page speed through the PageSpeed Insights API for mobile and desktop: performance score, LCP, CLS, INP or TBT, for the home page and the top 5 pages. | P0 |
| FR-AUD-05 | Mobile-friendliness: viewport meta tag, font size and tap-target audits from Lighthouse results, responsive layout signals. | P0 |
| FR-AUD-06 | Produce a 0 to 100 score from weighted categories, and findings with severity (critical, high, medium, low), explanation and fix recommendation. | P0 |
| FR-AUD-07 | SSRF protection: only http and https, DNS resolved and checked against private, loopback and link-local ranges (including after redirects), response size and content-type limits. | P0 |
| FR-AUD-08 | Keep audit history and show a comparison with the previous audit (new, fixed and unchanged issues). | P0 |

**Social media**

| ID | Requirement | Pri |
| --- | --- | --- |
| FR-AUD-09 | Register social accounts per client (Facebook, Instagram, LinkedIn). Import performance exports as CSV or JSON using per-platform templates, with validation and a preview before saving. | P0 |
| FR-AUD-10 | Social analysis: follower growth, engagement rate, reach and impressions trend, posting cadence, best days and times, best formats, top and bottom posts. Metrics are computed deterministically; the AI model writes the insights on top of them. | P0 |

**Competitors**

| ID | Requirement | Pri |
| --- | --- | --- |
| FR-AUD-11 | Add up to 5 competitors per client. Each analysis captures PageSpeed scores, on-page signals, sitemap size, publishing cadence (sitemap lastmod), top keywords and topics (TF-IDF over titles, headings and meta), then runs a gap analysis against the client and an AI summary of opportunities. | P0 |

**Google integrations**

| ID | Requirement | Pri |
| --- | --- | --- |
| FR-AUD-12 | Connect Google through OAuth 2.0 (read-only scopes). Select a GA4 property and a Search Console site. Pull sessions, users, conversions, channels and top pages from GA4; clicks, impressions, CTR, average position and top queries and pages from Search Console. | P0 |
| FR-AUD-13 | Tokens are stored encrypted. The UI shows connection health and a reconnect prompt when the refresh token is rejected (see risk R-03). | P0 |
| FR-AUD-14 | Completed audit summaries and metrics are written into the RAG index for the client. | P0 |

### 7.4 Knowledge base and RAG (FR-RAG)

| ID | Requirement | Pri |
| --- | --- | --- |
| FR-RAG-01 | Upload PDF, DOCX, TXT or Markdown files (up to 10 MB) or paste text as client knowledge. Text is extracted, chunked and embedded in a background job. | P0 |
| FR-RAG-02 | Brand profile, audit summaries, approved content and approved strategies are ingested automatically. | P0 |
| FR-RAG-03 | Retrieval is hybrid: pgvector cosine similarity plus PostgreSQL full-text search, merged with reciprocal rank fusion, always filtered by tenant and client. | P0 |
| FR-RAG-04 | Duplicate content is skipped by content hash. Deleting a document removes its chunks. A re-index action is available. | P0 |
| FR-RAG-05 | Every strategy and content generation stores the chunk IDs it used, and the UI shows them as sources. | P0 |
| FR-RAG-06 | A small golden question set and a script report retrieval hit rate at k, documented in the repository. | P1 |

### 7.5 AI strategy generator (FR-STR)

| ID | Requirement | Pri |
| --- | --- | --- |
| FR-STR-01 | Generate a monthly strategy for a client and month from goals, latest audits, Google metrics, social metrics, competitor gaps, brand profile and retrieved context. Output: executive summary, objectives with KPIs, channel plan, risks. | P0 |
| FR-STR-02 | Generate tasks, each with title, description, priority (P1 to P4), effort estimate in hours, suggested role, due date and dependencies. Output is validated against a Pydantic schema, with up to 2 automatic repair retries. | P0 |
| FR-STR-03 | Generate a 30-day content calendar: date, channel, format, topic, target keyword, call to action and funnel stage. Items can be dragged to new dates. | P0 |
| FR-STR-04 | Use RAG per FR-RAG and display the sources used. | P0 |
| FR-STR-05 | One click sends generated tasks to the Kanban board, linked to the strategy. | P0 |
| FR-STR-06 | Strategies are versioned. Regeneration creates a new version; Managers approve one version per client and month. | P0 |
| FR-STR-07 | The model comes from the tenant's routing for the `strategy` task. The estimated and actual cost are shown. | P0 |
| FR-STR-08 | Generation streams progress to the UI over SSE. | P0 |

### 7.6 BYOM integration (FR-BYOM)

| ID | Requirement | Pri |
| --- | --- | --- |
| FR-BYOM-01 | Add a connection for OpenAI, Anthropic, Ollama or any OpenAI-compatible endpoint (base URL). A Test button validates the credentials and lists available models. | P0 |
| FR-BYOM-02 | API keys are encrypted at rest with Fernet, are write-only in the UI (only the last 4 characters are shown), and are never logged. | P0 |
| FR-BYOM-03 | Per-task routing: choose connection, model, temperature and max tokens for `strategy`, `content` and `analysis`, with an optional fallback connection. | P0 |
| FR-BYOM-04 | Each call records provider, model, task, client, tokens in and out, latency and estimated cost. A usage dashboard groups by day, client, task and model. | P0 |
| FR-BYOM-05 | Optional monthly budget per tenant: warning at 80 percent, optional hard stop at 100 percent. A pre-flight cost estimate is shown before large jobs. | P0 |
| FR-BYOM-06 | Local models: a cloud-hosted API cannot reach `localhost`. Ollama connections therefore need a reachable URL (tunnel) or a locally run API. This is documented in the in-app help and the README. | P0 |
| FR-BYOM-07 | Structured outputs use each provider's native mechanism (tool use or JSON mode) with schema validation in the gateway. | P0 |
| FR-BYOM-08 | Optional shared demo connection using a rate-limited free-tier key from environment variables. Disabled by default. | P2 |

### 7.7 Content generation (FR-CON)

| ID | Requirement | Pri |
| --- | --- | --- |
| FR-CON-01 | Generate blog posts (outline, then draft, 800 to 2000 words) and social posts for LinkedIn, Facebook, Instagram and X, respecting each platform's length and format rules. | P0 |
| FR-CON-02 | Brand voice consistency: the client's brand profile and sample text are always injected. A voice-consistency score combines rule checks (banned words, required terms) and an AI judge. | P0 |
| FR-CON-03 | SEO suggestions: target keyword, keyword usage, title and meta description proposals, heading structure, readability score, internal link suggestions from the crawl, and a 0 to 100 SEO score. | P0 |
| FR-CON-04 | Generate 2 to 5 variations (A, B, C...) that differ in hook, tone or call to action. Show side by side, mark a winner, and record results manually for later reports. | P0 |
| FR-CON-05 | Status workflow: draft, review, approved, published. Only Managers and Admins approve. | P0 |
| FR-CON-06 | Generate directly from a content calendar item in one click. | P0 |
| FR-CON-07 | Export as copy, Markdown or HTML. Publishing to WordPress is covered by FR-INT-01. | P0 |

### 7.8 Team collaboration (FR-COL)

| ID | Requirement | Pri |
| --- | --- | --- |
| FR-COL-01 | Kanban board (To do, Doing, Review, Done) with drag and drop, ordering and filters by client, assignee and priority. | P1 |
| FR-COL-02 | Assign tasks, set due dates, comment, and @mention teammates (in-app notifications). | P1 |
| FR-COL-03 | Real-time updates through WebSockets with Redis pub/sub fan-out, presence indicators, and optimistic updates with version-based conflict detection. | P1 |
| FR-COL-04 | Team performance analytics: tasks completed, on-time rate, cycle time, workload per member and per client, for a selectable period. | P1 |
| FR-COL-05 | Project progress: strategy completion percentage and burndown per client and month. | P1 |

### 7.9 Automated reporting (FR-REP)

| ID | Requirement | Pri |
| --- | --- | --- |
| FR-REP-01 | Build a monthly report per client from selectable sections: executive summary, audit score trend, traffic, search performance, social, content, tasks completed, next month plan. | P1 |
| FR-REP-02 | Month-over-month comparison charts and deltas for key metrics, computed deterministically from stored data. | P1 |
| FR-REP-03 | AI-written insights and recommendations grounded in the report data and routed through the `analysis` task model. | P1 |
| FR-REP-04 | Generate a PDF with the tenant's white-label branding (logo, color, footer) and no platform branding. | P1 |
| FR-REP-05 | Share a read-only report through an expiring tokenized link, or download the PDF. | P1 |
| FR-REP-06 | Schedule automatic monthly generation with Celery beat. | P2 |

### 7.10 Integrations (FR-INT)

| ID | Requirement | Pri |
| --- | --- | --- |
| FR-INT-01 | WordPress: connect with site URL and application password; create drafts or publish posts with title, content, categories and SEO meta. | P1 |
| FR-INT-02 | Trello: connect with API key and token; push Kanban tasks to board lists. Two-way sync is P2. | P1 |
| FR-INT-03 | Asana: connect with a personal access token; push tasks to a project. | P1 |
| FR-INT-04 | Facebook, Instagram, LinkedIn: all platforms are served by the P0 import in FR-AUD-09. A `SocialSource` interface allows an OAuth adapter to pull insights directly once an app is approved. | P1 |
| FR-INT-05 | Integration credentials are encrypted, have a health check, and can be disconnected, which deletes stored secrets. | P1 |

## 8. API Design

Base path `/api/v1`. JSON over HTTPS. OpenAPI and Swagger UI are generated by FastAPI at `/docs` and exported to `docs/API.md`.

**Conventions**

- Authentication: `Authorization: Bearer <access token>`; tenant comes from the token, never from the URL or body.
- Errors use RFC 7807 `application/problem+json`. Lists use cursor pagination with `limit` and `cursor`.
- Job-creating POST requests accept an `Idempotency-Key` header and return `202` with a `job_id`.
- Rate limits per user and per tenant are enforced with Redis counters.

| Area | Endpoints |
| --- | --- |
| Auth | POST `/auth/register`, `/auth/login`, `/auth/refresh`, `/auth/logout`, `/auth/switch-tenant`, `/auth/accept-invite`; GET `/auth/me` |
| Tenant | GET and PATCH `/tenant`; GET `/members`; POST `/members/invite`; PATCH and DELETE `/members/{id}`; PUT `/tenant/branding` |
| Clients | GET and POST `/clients`; GET, PATCH and DELETE `/clients/{id}`; GET and PUT `/clients/{id}/brand-profile` |
| Knowledge | POST `/clients/{id}/documents` (upload or text); GET `/clients/{id}/documents`; DELETE `/documents/{id}`; POST `/clients/{id}/search` |
| Audits | POST `/clients/{id}/audits` (type website, social or competitor); GET `/clients/{id}/audits`; GET `/audits/{id}`; GET `/audits/{id}/findings`; GET `/audits/{id}/compare/{otherId}` |
| Social | POST `/clients/{id}/social-accounts`; POST `/social-accounts/{id}/import` (CSV or JSON); GET `/social-accounts/{id}/metrics` |
| Competitors | GET and POST `/clients/{id}/competitors`; DELETE `/competitors/{id}` |
| Google | GET `/integrations/google/authorize`; GET `/integrations/google/callback`; GET `/integrations/google/properties`; POST `/clients/{id}/google/link`; GET `/clients/{id}/analytics` |
| Strategy | POST `/clients/{id}/strategies`; GET `/clients/{id}/strategies`; GET `/strategies/{id}`; POST `/strategies/{id}/approve`; POST `/strategies/{id}/push-tasks`; PATCH `/calendar-items/{id}` |
| Content | POST `/clients/{id}/content` (generate); GET `/content/{id}`; PATCH `/content/{id}`; POST `/content/{id}/variations`; POST `/content/{id}/seo-analysis`; POST `/content/{id}/approve`; POST `/content/{id}/publish` |
| AI models | GET and POST `/ai/connections`; POST `/ai/connections/{id}/test`; DELETE `/ai/connections/{id}`; GET and PUT `/ai/routes`; GET `/ai/usage`; GET `/ai/usage/estimate` |
| Tasks | GET and POST `/tasks`; PATCH `/tasks/{id}`; POST `/tasks/{id}/comments`; GET `/analytics/team`; GET `/analytics/progress` |
| Reports | POST `/clients/{id}/reports`; GET `/reports/{id}`; GET `/reports/{id}/pdf`; POST `/reports/{id}/share`; GET `/public/reports/{token}` (no auth, read only) |
| Integrations | GET `/integrations`; POST `/integrations/{provider}`; DELETE `/integrations/{provider}`; POST `/integrations/{provider}/test` |
| Jobs and realtime | GET `/jobs/{id}`; DELETE `/jobs/{id}` (cancel); SSE `/jobs/{id}/events`; SSE `/notifications/stream`; WebSocket `/ws/tasks` |
| Platform | GET `/health`, `/ready` |

## 9. Non-Functional Requirements

| ID | Category | Requirement |
| --- | --- | --- |
| NFR-01 | Performance | p95 latency under 300 ms for read endpoints; a 100-page audit completes in under 5 minutes; strategy generation completes in under 90 seconds with a cloud model; SSE events arrive within 1 second of being published. |
| NFR-02 | Scalability | Stateless API containers; workers scale horizontally; all queries are indexed on `tenant_id` and foreign keys; HNSW index on embeddings; cursor pagination everywhere. Connection pooling uses the Neon pooled URL for the API and the direct URL for migrations. |
| NFR-03 | Pooling safety | Tenant context is set with `set_config('app.tenant_id', value, true)` inside each transaction, which is safe with transaction-mode pooling. Session-level `SET` is never used. asyncpg prepared-statement caching is disabled when using the pooler. |
| NFR-04 | Availability | `/health` and `/ready` endpoints; graceful shutdown; job retries with backoff; a scheduled GitHub Actions ping reduces cold starts on the free tier. |
| NFR-05 | Usability | First-run onboarding wizard: create agency, add client, connect an AI model, run the first audit. Helpful empty states, loading skeletons, clear error messages. |
| NFR-06 | Accessibility | WCAG 2.1 AA target: keyboard operable (including Kanban through the dnd-kit keyboard sensor), visible focus, color contrast 4.5:1, labelled form controls, `aria-live` for job progress, automated axe checks in CI. |
| NFR-07 | Responsiveness | Fully usable from 360 px wide screens; tables collapse to cards on mobile; Kanban scrolls horizontally. |
| NFR-08 | Maintainability | Typed code (mypy and strict TypeScript), ruff and ESLint clean, at least 80 percent coverage on core modules (auth, tenancy, ai\_gateway, rag), architecture decisions recorded in `docs/DECISIONS.md`. |
| NFR-09 | Observability | Structured JSON logs with request ID, tenant ID and job ID; secrets redacted; optional Sentry free tier. |
| NFR-10 | Data protection | Tenant data export and tenant deletion (GDPR-minded). Raw crawl data is retained 90 days; usage logs 12 months. |
| NFR-11 | Portability | Everything runs from `docker compose up` with seed data; no vendor-specific code outside `infrastructure` adapters. |
| NFR-12 | Documentation | README, architecture, API reference, deployment guide, `.env.example`, code comments on non-obvious logic, and a demo script. |

## 10. AI and RAG Design Details

### 10.1 Task types and structured outputs

| Task | Used by | Output schema (Pydantic) |
| --- | --- | --- |
| `strategy` | Strategy, calendar, tasks | `StrategyPlan` (summary, objectives with KPIs, channels, risks), `TaskPlan[]`, `CalendarPlan[]` |
| `content` | Blog, social, variations | `ContentDraft` (title, body, meta, keywords), `Variation[]` |
| `analysis` | Audit insights, competitor summary, report insights | `InsightSet` (insights with evidence references, recommendations with priority) |

Each generation runs as separate, smaller calls (strategy, then tasks, then calendar) so that each output stays valid and cheap, and so that smaller local models still work. Invalid JSON triggers up to two repair retries that include the validation error.

### 10.2 Prompt assembly

System rules, then brand profile, then structured facts (audit scores, metrics, competitor gaps), then retrieved chunks inside clearly delimited blocks, then the output schema. Facts are passed as computed numbers; the model explains and prioritizes them instead of inventing metrics.

### 10.3 Retrieval details

- Chunk size about 500 tokens with 80 overlap, boundary-aware (headings and paragraphs).
- Hybrid search: top 20 from vector search and top 20 from full-text search, fused with reciprocal rank fusion, reduced to 8 chunks within a token budget.
- Metadata filters: `tenant_id` (enforced by RLS), `client_id`, `source_type`, recency boost for audits and metrics.

### 10.4 Safety and quality controls

- **Prompt injection:** crawled pages, uploaded files and imported CSVs are untrusted data. They are delimited, labelled as data, stripped of control sequences, and never allowed to trigger tool calls or change system rules.
- **Grounding:** generated numbers must come from supplied facts; a post-check flags any figure not present in the input.
- **Cost control:** token budgets per task, response caching of identical audit prompts for 24 hours, PageSpeed result caching for 24 hours, tenant monthly budget (FR-BYOM-05).
- **Determinism:** temperature defaults 0.3 for analysis, 0.7 for content, configurable per route.

## 11. Security Design

| Threat | Control |
| --- | --- |
| Cross-tenant data access | JWT tenant claim, server RBAC, RLS with `FORCE`, non-owner database role, isolation test suite, tenant-scoped cache keys and vector queries |
| Token theft | 15-minute access tokens kept in memory; refresh token in an `HttpOnly`, `Secure`, `SameSite=Lax` cookie set by the Next.js server through a same-origin proxy (`/api/*` rewrite), so cookies are first-party on the Vercel domain |
| Streaming auth | SSE and WebSocket connect straight to the API (a Vercel rewrite cannot proxy WebSockets) using a 60-second single-use stream ticket from `POST /auth/stream-ticket` |
| Stored secrets (AI keys, OAuth tokens, integration credentials) | Fernet encryption, key in environment, rotation supported through multi-key decrypt; never returned by the API; redacted from logs |
| SSRF through the crawler | Scheme allowlist, DNS resolution checks against private ranges before and after redirects, size and time limits, no cookies forwarded |
| Injection and XSS | SQLAlchemy parameterization, Pydantic validation, output encoding, strict Content Security Policy, sanitized HTML for generated content |
| Brute force and abuse | Redis rate limits per IP, user and tenant; login lockout; job quotas per tenant |
| File upload risks | Extension and MIME checks, size limit, text extraction in the worker, files not served back as executable content |
| Shared report links | 256-bit random token, expiry, revocation, read-only data only |
| Supply chain | Locked dependencies, Dependabot, `pip-audit`, `pnpm audit`, secret scanning in CI |
| CORS and CSRF | Explicit origin allowlist; refresh cookie endpoints require a custom header and same-site policy |

## 12. Deployment and CI/CD

### 12.1 Environments

| Environment | Stack |
| --- | --- |
| Local | Docker Compose: `pgvector/pgvector:pg16`, `redis:7-alpine`, API, worker, web |
| Production demo | Vercel (web), Render Docker web service (API plus worker through supervisord), Neon (Postgres 16 with pgvector), Render Key Value or Upstash (Redis) |

### 12.2 Configuration (names only, values in the host dashboards)

`DATABASE_URL` (pooled), `DATABASE_URL_DIRECT`, `REDIS_URL`, `JWT_SECRET` (or RS256 key pair), `FERNET_KEYS`, `ALLOWED_ORIGINS`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI`, `PAGESPEED_API_KEY`, `SMTP_URL` (optional), `NEXT_PUBLIC_API_URL`, `API_INTERNAL_URL`, `DEMO_AI_KEY` (optional).

### 12.3 Pipeline

1. Pull request: ruff, mypy, pytest (with Postgres and Redis service containers), ESLint, TypeScript check, Vitest, Playwright smoke test, Docker build, Alembic check that migrations match models.
2. Merge to main: Vercel deploys the web app; Render builds the image and runs `alembic upgrade head` before starting.
3. Scheduled workflow: keep-warm ping and a nightly demo data reset.

### 12.4 Free-tier operating notes

The worker runs with `--pool=solo` and concurrency 1 to fit 512 MB. The embedding model is loaded lazily and cached. Render free services sleep after inactivity, and free limits change over time, so check current limits before relying on them and open the demo a few minutes before presenting.

## 13. Testing Strategy

| Level | Scope | Tools |
| --- | --- | --- |
| Unit | Scoring, chunking, cost calculation, prompt builders, CSV parsers, RBAC rules | pytest, Vitest |
| Integration | API with real Postgres and Redis: auth flow, CRUD, jobs, RAG retrieval | pytest-asyncio, service containers |
| Isolation | Two tenants; every router and the vector search are probed for cross-tenant reads and writes | pytest (`tests/isolation`) |
| Provider contract | OpenAI, Anthropic and Ollama adapters against recorded HTTP fixtures; a fake provider for deterministic pipelines | respx |
| Retrieval evaluation | Golden questions, hit rate at k | Script in `tests/rag_eval` |
| End to end | Register, add client, connect model, audit, strategy, content, Kanban, report | Playwright |
| Accessibility | Axe scans of core pages | axe with Playwright |
| Load smoke | 50 concurrent users on read endpoints and 5 concurrent jobs | k6 or Locust |

## 14. Business Model and Evaluation Mapping

### 14.1 Revenue model (for the business impact criterion)

| Plan | Target | Limits (enforced in code, billing mocked in MVP) |
| --- | --- | --- |
| Free | Freelancers | 1 client, 2 members, 5 audits per month |
| Pro | Small agencies | 10 clients, 10 members, unlimited audits, white-label reports |
| Agency | Larger agencies | Unlimited clients, SSO and API access (roadmap), priority support |
| Because AI usage is billed to the customer through BYOM, gross margin stays high; revenue comes from seats and client slots. Plan limits are implemented as tenant-level quotas so the model is demonstrable even without a payment provider. |  |  |

### 14.2 Success metrics from the statement

| Statement success metric | How it is met |
| --- | --- |
| Functional multi-tenant platform with authentication | FR-AUTH, FR-TEN |
| Working AI integrations producing marketing insights | FR-STR, FR-CON, FR-AUD-10, FR-AUD-11 |
| BYOM with external models | FR-BYOM |
| Automated audit for website or social | FR-AUD (both) |
| Clean, intuitive UI | NFR-05 to NFR-07 |
| Scalable architecture for multiple users | Sections 3 and 9 |
| Data security and tenant isolation | Sections 3.4, 11 and the isolation tests |

### 14.3 Evaluation criteria evidence

| Criterion (weight) | Evidence to show |
| --- | --- |
| Technical excellence (30%) | Modular architecture, RLS isolation tests, database schema, OpenAPI docs, CI |
| Innovation and AI (25%) | Hybrid RAG with visible sources, BYOM gateway with per-task routing and cost tracking, grounded structured generation |
| User experience (20%) | Onboarding wizard, mobile layout, accessibility checks, live progress |
| Business impact (15%) | Value proposition, plan model, zero AI cost to the platform |
| Completeness and demo (10%) | Seeded live demo, README, architecture doc, 10-minute script |

### 14.4 Submission checklist

Public GitHub repository with documentation; live demo with sample data and demo logins; 10-minute pitch deck with technical demo; architecture overview and setup instructions (this document and `docs/`).

## 15. Delivery Plan and Demo Script

### 15.1 Phases (assumes about four weeks; scale to the event window)

| Phase | Focus | Exit criteria |
| --- | --- | --- |
| 1. Foundation | Monorepo, Compose stack, auth, tenants, RBAC, RLS, isolation tests, CI, first deploy | Two tenants log in on the deployed app and cannot see each other's data |
| 2. AI core | AI gateway and BYOM UI, RAG ingestion and retrieval, usage tracking | A strategy prompt runs on the user's own key with sources and cost recorded |
| 3. Audit engine | Crawler, SEO checks, PageSpeed, social import, competitors, Google OAuth | One full website audit plus a social and competitor audit with findings |
| 4. Generators | Strategy, tasks, 30-day calendar, content, variations, SEO scoring | Audit to strategy to calendar to content works end to end |
| 5. Collaboration and reports | Kanban, real-time, analytics, PDF reports, WordPress, Trello, Asana | A white-label PDF with month-over-month charts |
| 6. Polish | Seed data, accessibility, performance, docs, pitch, rehearsal | Demo runs from a cold start in under 3 minutes of setup |
| If time runs short, cut in this order: FR-REP-06, Asana (FR-INT-03), two-way Trello sync, WebSocket presence. P0 requirements are never cut. |  |  |

### 15.2 Ten-minute demo script

1. Register an agency and invite a Manager (1 min). 2. Add a client with brand profile and knowledge documents (1 min). 3. Connect a model and set per-task routing (1 min). 4. Run a website audit with live progress; open findings (2 min). 5. Generate the strategy with sources, tasks and the 30-day calendar (2 min). 6. Generate content with variations and SEO score; publish to WordPress (1 min). 7. Kanban in two browser windows with real-time updates (1 min). 8. Generate and open the white-label PDF report; show usage and cost (1 min).

## 16. Risks

| ID | Risk | Mitigation |
| --- | --- | --- |
| R-01 | Free-tier cold starts and sleeping services | Keep-warm ping, warm up before demo, loading states |
| R-02 | Free-tier quota changes (Render, Neon, Redis) | Verify limits at the start; Docker Compose fallback; portable adapters |
| R-03 | Google OAuth apps in Testing mode issue refresh tokens that expire after about 7 days, allow a limited number of test users and show an unverified-app screen | Add demo accounts as test users, reconnect before the demo, cache last successful metrics, include recorded sample data as fallback |
| R-04 | 512 MB memory limit | Lazy model loading, worker concurrency 1, crawl batching, streaming PDF generation |
| R-05 | LLM returns invalid or low-quality output | Schema validation, repair retries, smaller staged prompts, grounded facts |
| R-06 | Scope too large for the time | Strict P0 first order (15.1), vertical slices, cut list |
| R-07 | Crawler abuse or SSRF | Section 11 controls, per-tenant quotas |
| R-08 | Ollama not reachable from the cloud API | Documented tunnel setup; local Compose option |
| R-09 | Prompt injection through crawled content | Section 10.4 controls |
| R-10 | Dependency drift or incompatibility | Lock files, grouped updates, CI install with frozen lockfiles |

## 17. Open Questions and Assumptions to Confirm

1. **Product name:** *MarketPilot* is a working name.
2. **Team size and timeline:** the plan in 15.1 assumes about four weeks and a small team.
3. **Social platforms:** CSV or JSON import is the P0 path; live OAuth for Facebook, Instagram and LinkedIn depends on app approval.
4. **Email delivery:** invitations work through copyable links; a real email provider is optional.
5. **Billing:** plan limits are enforced but payments are mocked.
6. **Language support:** English only for MVP.
