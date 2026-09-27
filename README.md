# Pi-Vend

An SEO and listing agent for Korean marketplace sellers (네이버 스마트스토어, 쿠팡), built on the [Pi](https://github.com/badlogic/pi-mono) agent toolkit.

It's a multi-user platform: sellers sign up, connect their own AI model and Naver API keys, and work with their own data. The seller chats with the agent. It then:

- researches keywords with Naver's official APIs: search volume, related keywords, trends, and competition (경쟁강도 = listings ÷ monthly searches)
- analyzes what the top Naver Shopping listings for a query look like (prices, title words, categories)
- writes and checks product titles (상품명) and tags
- writes a 상세페이지 as structured sections, renders it to 860px JPG slices, and saves everything as a draft the seller approves

Each user picks their model: Claude, OpenAI or Gemini with their own API key, or their own llama.cpp / OpenAI-compatible server.

```
Browser ── Django (Python) ─────────────── Postgres / SQLite
            │ accounts, sign-up, encrypted per-user API keys
            │ drafts, conversations, admin
            │ Naver API clients (user's keys) + per-user cache
            │ Playwright renderer (상세페이지 → JPG)
            │ /internal/* API  ◄──────────────┐ tools call back with a shared token
            │                                 │
            └─ /chat → SSE proxy ──► Agent service (Node, pi-agent-core + pi-ai)
                                       stateless; Django sends the transcript and
                                       the user's model settings (key included)
                                       with each turn; nothing is kept afterwards
                                       LLM: Claude | OpenAI | Gemini | user's server
```

Why the split: most of the product is data work (API signing, caching, Korean text processing, rendering), which Python handles well. Pi is TypeScript, so the agent loop runs as a small Node service. Its tools are thin wrappers over Django endpoints. It never stores credentials: the user's LLM key arrives with each request, and Naver calls happen in Django with that user's keys.

## Accounts and keys

- **Sign-up** with email and password, email verification (24h link), password reset, password change and account deletion (removes stores, drafts and their images, conversations and keys). `SIGNUPS_OPEN=0` makes it invite-only; admins can still add users.
- **설정 › API 연결**: each user connects an AI model (provider, key, model; or a server URL for llama.cpp / OpenAI-compatible), the 네이버 검색광고 API and the 네이버 개발자센터 API. "저장하고 테스트" makes a small real call and shows the result. Keys are encrypted at rest with Fernet (`CREDENTIAL_ENCRYPTION_KEYS`, rotatable with `manage.py rotate_credentials`), never shown again after saving, and never logged.
- **Isolation**: every query is scoped to the signed-in user. Naver responses are cached per user, so one seller's quota never serves another. User-supplied LLM URLs that resolve to private or internal addresses are refused (checked in Django on save and in the agent on every request), unless `ALLOW_PRIVATE_LLM_URLS=1` for single-tenant self-hosting.
- **Limits**: per-user hourly limits on chat messages and research lookups, and per-IP limits on sign-up and emails. Point `CACHE_URL` at Redis or the database cache when running several processes.
- A **시작하기** checklist on the dashboard and settings page walks new users through the four steps.

## The app

A seller workspace, not a chat window. The agent sits in a drawer on every page and gets prompts from what you're looking at.

- **대시보드**: the store's own numbers for 7/30/90 days against the previous period. Revenue as the hero figure with a daily chart (hover crosshair, table view), orders, AOV, conversion and ad ROAS tiles with sparklines, products by revenue with share and change, channel split, weekday pattern, inflow keywords cross-referenced with Naver search volume (capture share), ad ROAS by keyword, and a market-demand watch. A **다음 액션** column turns the numbers into rule-based insights ("광고 '여름원피스' ROAS 92%"), each with an "에이전트에게 맡기기" button.
- **데이터 연결**: upload 스마트스토어 / 쿠팡 report exports (CSV in UTF-8 or CP949, or XLSX). Columns are recognized by Korean/English header synonyms, title rows are skipped, and re-importing a period replaces it. Four report kinds: 판매 실적, 방문 통계, 유입 키워드, 광고 성과.
- **상품 초안**: listing drafts with a 상품명 check, phone-frame 상세페이지 preview, and zip download.
- **키워드 리서치**: volume, competition, trend, related keywords, competitor prices and title words.
- **에이전트**: full-page conversations, or the drawer. It can read the store numbers (`store_overview` tool) as well as research data.

Two skins share the same markup: **네오브루탈** (default; paper and ink, pill controls, pastel bento tiles, hard shadows on interaction) and **기본** (neutral). Switch with the wand button in the sidebar footer. Both have light and dark themes and a mobile layout. Chart colors follow a colorblind-validated palette in both skins.

To explore without real data, click "데모 데이터로 둘러보기" on the empty dashboard, or run `python manage.py seed_demo_store --user <name>`.

## Quick start (local)

Requirements: Python 3.11+ with [uv](https://docs.astral.sh/uv/), Node.js 22.19+.

```bash
cp .env.example .env          # defaults work for local development

# Backend
cd backend
uv sync
uv run playwright install chromium   # or set PLAYWRIGHT_CHROMIUM_EXECUTABLE
uv run python manage.py migrate
uv run python manage.py createsuperuser   # optional: an admin account
uv run python manage.py runserver

# Agent (second terminal)
cd agent
npm install
npm start
```

Open http://localhost:8000/signup/ and create an account. With the default console mail backend, the verification link is printed in the Django terminal. Then connect your keys in **설정 › API 연결**. The **키워드 리서치** page runs the same research without the agent.

## Models

Users choose a provider in **설정 › API 연결**:

| Provider | What the user enters | Default model |
|---|---|---|
| Claude (Anthropic) | API key | `claude-opus-5` |
| OpenAI | API key | `gpt-5.5` |
| Gemini (Google) | API key | `gemini-3.5-flash` |
| llama.cpp 서버 | server URL, optional key | whatever `llama-server` has loaded |
| OpenAI 호환 서버 | server URL, optional key | the model they name, or the first one the server lists |

The model field suggests the ids pi-ai knows for each cloud provider. Model settings travel with each chat request, so users on different providers share one agent service.

**Local models.** A hosted Pi-Vend can only reach a user's server on a public URL; `localhost` on the seller's PC is not reachable. For a single-tenant install on your own machine, set `ALLOW_PRIVATE_LLM_URLS=1` and connect e.g. `http://localhost:8080/v1`. Start llama-server with `--jinja` so the chat template handles tool calls:

```bash
llama-server -m your-model.gguf --jinja -c 32768 --port 8080
```

For Qwen3-style thinking models, tick "추론(thinking) 모델이에요". Tool use needs a model that is good at function calling; small models will struggle with the multi-step flows.

## Naver API keys (per user)

| Key | Where | Used for |
|---|---|---|
| 검색광고 API: 액세스라이선스, 비밀키, CUSTOMER_ID | [searchad.naver.com](https://searchad.naver.com) → 도구 → API 사용 관리 | Keyword tool: monthly search volume, related keywords |
| 개발자센터: Client ID/Secret | [developers.naver.com](https://developers.naver.com) application with **검색** and **데이터랩** | Shopping search (listing counts, competitors), trends |

Both are free. The settings page shows these steps next to the form. Responses are cached per user for `RESEARCH_CACHE_HOURS` (default 24). See [docs/data-sources.md](docs/data-sources.md) for what the marketplaces do and don't expose.

## Docker

```bash
cp .env.example .env   # set DJANGO_DEBUG=0, DJANGO_SECRET_KEY, AGENT_INTERNAL_TOKEN,
                       # CREDENTIAL_ENCRYPTION_KEYS, EMAIL_URL, DJANGO_ALLOWED_HOSTS, PUBLIC_BASE_URL
docker compose up --build
docker compose exec web python manage.py createsuperuser   # optional: an admin account
```

The web container refuses to start without valid `CREDENTIAL_ENCRYPTION_KEYS` (`manage.py check --deploy`). Back the keys up with the database: without them, stored API keys can't be decrypted and users have to enter them again.

To self-host a local model for yourself: put a GGUF file in `./models`, set `LLAMA_MODEL_FILE=<file>` and `ALLOW_PRIVATE_LLM_URLS=1`, start with `docker compose --profile local up --build`, and connect "llama.cpp 서버" with `http://llamacpp:8080/v1`.

Marketplace APIs only accept registered caller IPs (Naver Commerce: 3, Coupang: 10). Deploy the web service behind a fixed egress IP before connecting seller stores.

## Tests

```bash
cd backend && uv run pytest     # the real Chromium render test is skipped if no browser is installed
cd agent && npm test && npm run typecheck
```

Backend tests include sign-up and verification, encrypted keys and rotation, connection checks, rate limits, and cross-user isolation (another user's drafts, conversations, stores, keys and cache are unreachable through pages, the internal API and the agent). The agent tests run the full loop with Pi's scripted faux provider and against a mock `llama-server` that streams tool calls, check that the user's key reaches the provider, and that private LLM URLs are refused.

## Layout

```
backend/
  config/              settings, urls
  pivend/accounts/     sign-up, login, encrypted per-user credentials, connection checks, rate limits, settings pages
  pivend/naver/        검색광고 + open API clients (signing, parsing)
  pivend/research/     keyword stats, related keywords, trends, competitor analysis, cache
  pivend/listings/     drafts, 상품명 checker, 상세페이지 spec + renderer + template
  pivend/store/        store data: models, report importer, dashboard analytics, insights, demo generator
  pivend/assistant/    conversations, chat SSE proxy, /internal API for the agent
  pivend/web/          pages (login, research, drafts), SVG chart geometry, UI template tags
  pivend/web/static/   app.css (base design system), brutal.css (neobrutalist skin), chat.js, charts.js, app.js, icons, Pretendard
agent/
  src/llm.ts           per-request model setup from the user's settings (cloud + llama.cpp / OpenAI-compatible), URL guard
  src/tools.ts         tool definitions (TypeBox schemas) → Django internal API
  src/prompt.ts        system prompt: Korean marketplace SEO rules + honesty rules
  src/chat.ts          one stateless chat turn → UI events
  src/server.ts        HTTP/SSE server
```

## Roadmap

1. **Validate the importer against real exports**: header synonyms were written from integrator docs; adjust `pivend/store/importers.py` as real 비즈어드바이저 / WING files come in.
2. **Store connections**: register as a Naver 커머스솔루션 and a Coupang 연동업체, let users connect their stores in 설정 › API 연결, sync products and orders (Celery beat), and publish approved drafts through the Commerce API and WING API. Both require a fixed egress IP.
3. **Plans and billing**: optional platform-provided keys as a fallback (the lookup is centralized in `pivend/accounts/services.py`), with usage metering per account.
4. **Rank tracking** from shopping search snapshots, and keyword volume history.
5. Image generation and background removal for product shots.

Bundled third-party assets: [Pretendard](https://github.com/orioncactus/pretendard) (OFL-1.1), icons from [Lucide](https://lucide.dev) (ISC), [marked](https://github.com/markedjs/marked) (MIT) and [DOMPurify](https://github.com/cure53/DOMPurify) (Apache-2.0 / MPL-2.0).
