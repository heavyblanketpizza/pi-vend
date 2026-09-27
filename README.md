# Pi-Vend

An SEO and listing agent for Korean marketplace sellers (네이버 스마트스토어, 쿠팡), built on the [Pi](https://github.com/badlogic/pi-mono) agent toolkit.

The seller chats with the agent. It then:

- researches keywords with Naver's official APIs: search volume, related keywords, trends, and competition (경쟁강도 = listings ÷ monthly searches)
- analyzes what the top Naver Shopping listings for a query look like (prices, title words, categories)
- writes and checks product titles (상품명) and tags
- writes a 상세페이지 as structured sections, renders it to 860px JPG slices, and saves everything as a draft the seller approves

The agent can run on Claude, OpenAI, Gemini, or a local model served by llama.cpp.

```
Browser ── Django (Python) ─────────────── Postgres / SQLite
            │ auth, drafts, conversations, admin
            │ Naver API clients + response cache
            │ Playwright renderer (상세페이지 → JPG)
            │ /internal/* API  ◄──────────────┐ tools call back with a shared token
            │                                 │
            └─ /chat → SSE proxy ──► Agent service (Node, pi-agent-core + pi-ai)
                                       stateless; Django sends the transcript
                                       with each turn and stores the result
                                       LLM: Claude | OpenAI | Gemini | llama.cpp
```

Why the split: most of the product is data work (API signing, caching, Korean text processing, rendering), which Python handles well. Pi is TypeScript, so the agent loop runs as a small Node service. Its tools are thin wrappers over Django endpoints, and it never holds marketplace credentials.

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
cp .env.example .env          # set an LLM key and your Naver API keys

# Backend
cd backend
uv sync
uv run playwright install chromium   # or set PLAYWRIGHT_CHROMIUM_EXECUTABLE
uv run python manage.py migrate
uv run python manage.py createsuperuser
uv run python manage.py runserver

# Agent (second terminal)
cd agent
npm install
npm start
```

Open http://localhost:8000, log in, and start a conversation. The **키워드 리서치** page runs the same research without the agent.

## Choosing the model

Set `LLM_PROVIDER` in `.env`:

| Provider | Settings | Default model |
|---|---|---|
| `anthropic` | `ANTHROPIC_API_KEY` | `claude-opus-5` |
| `openai` | `OPENAI_API_KEY` | `gpt-5.5` |
| `google` | `GEMINI_API_KEY` | `gemini-3.5-flash` |
| `llamacpp` | `LLM_BASE_URL` (default `http://localhost:8080/v1`) | whatever `llama-server` has loaded |
| `openai-compatible` | `LLM_BASE_URL`, optional `LLM_API_KEY` | set `LLM_MODEL` |

Override the model with `LLM_MODEL`. If you name a model that doesn't exist, the agent lists the valid ones at startup.

**llama.cpp.** Start the server with `--jinja` so the model's chat template handles tool calls:

```bash
llama-server -m your-model.gguf --jinja -c 32768 --port 8080
```

For Qwen3-style thinking models, also set `LLM_REASONING=true` and `LLM_THINKING_FORMAT=qwen-chat-template`. Tool use needs a model that is good at function calling, and small models will struggle with the multi-step flows.

## Naver API keys

| Key | Where | Used for |
|---|---|---|
| `NAVER_SEARCHAD_*` | [searchad.naver.com](https://searchad.naver.com) → 도구 → API 사용 관리 | Keyword tool: monthly search volume, related keywords |
| `NAVER_CLIENT_ID/SECRET` | [developers.naver.com](https://developers.naver.com) application with **검색** and **데이터랩** | Shopping search (listing counts, competitors), trends |

Responses are cached in the database for `RESEARCH_CACHE_HOURS` (default 24) to stay within daily quotas. Before offering the service commercially, check each API's terms on reuse. See [docs/data-sources.md](docs/data-sources.md) for what the marketplaces do and don't expose.

## Docker

```bash
cp .env.example .env   # set DJANGO_DEBUG=0, DJANGO_SECRET_KEY, AGENT_INTERNAL_TOKEN, keys
docker compose up --build
docker compose exec web python manage.py createsuperuser
```

To run a local model: put a GGUF file in `./models`, then set `LLAMA_MODEL_FILE=<file>`, `LLM_PROVIDER=llamacpp` and `LLM_BASE_URL=http://llamacpp:8080/v1`. Start everything with `docker compose --profile local up --build`. If llama-server runs on the host instead, use `LLM_BASE_URL=http://host.docker.internal:8080/v1`.

Marketplace APIs only accept registered caller IPs (Naver Commerce: 3, Coupang: 10). Deploy the web service behind a fixed egress IP before connecting seller stores.

## Tests

```bash
cd backend && uv run pytest     # the real Chromium render test is skipped if no browser is installed
cd agent && npm test && npm run typecheck
```

The agent tests run the full loop twice. One run uses Pi's scripted faux provider. The other uses a mock `llama-server` that streams tool calls, which exercises the real OpenAI-compatible code path.

## Layout

```
backend/
  config/              settings, urls
  pivend/naver/        검색광고 + open API clients (signing, parsing)
  pivend/research/     keyword stats, related keywords, trends, competitor analysis, cache
  pivend/listings/     drafts, 상품명 checker, 상세페이지 spec + renderer + template
  pivend/store/        store data: models, report importer, dashboard analytics, insights, demo generator
  pivend/assistant/    conversations, chat SSE proxy, /internal API for the agent
  pivend/web/          pages (login, research, drafts), SVG chart geometry, UI template tags
  pivend/web/static/   app.css (base design system), brutal.css (neobrutalist skin), chat.js, charts.js, app.js, icons, Pretendard
agent/
  src/llm.ts           provider setup (cloud + llama.cpp / OpenAI-compatible)
  src/tools.ts         tool definitions (TypeBox schemas) → Django internal API
  src/prompt.ts        system prompt: Korean marketplace SEO rules + honesty rules
  src/chat.ts          one stateless chat turn → UI events
  src/server.ts        HTTP/SSE server
```

## Roadmap

1. **Validate the importer against real exports**: header synonyms were written from integrator docs; adjust `pivend/store/importers.py` as real 비즈어드바이저 / WING files come in.
2. **Store connections**: register as a Naver 커머스솔루션 and a Coupang 연동업체, sync products and orders (Celery beat), and publish approved drafts through the Commerce API and WING API.
3. **Rank tracking** from shopping search snapshots, and keyword volume history.
4. Image generation and background removal for product shots.

Bundled third-party assets: [Pretendard](https://github.com/orioncactus/pretendard) (OFL-1.1), icons from [Lucide](https://lucide.dev) (ISC), [marked](https://github.com/markedjs/marked) (MIT) and [DOMPurify](https://github.com/cure53/DOMPurify) (Apache-2.0 / MPL-2.0).
