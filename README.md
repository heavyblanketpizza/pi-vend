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

- **Agent**: a streaming chat. Tool calls show up as a live activity list (검색량 조회, 상품명 점검, 상세페이지 렌더링…), rendered detail pages appear as preview cards, and conversations are grouped by date in the sidebar.
- **키워드 리서치**: monthly volume with the PC/mobile split, listing count, competition ratio, a 12-month trend chart, sortable related keywords, price distribution, the words top listings use, their category share, and the top 10 listings.
- **상품 초안**: card grid with render thumbnails. Each draft page has a live 상품명 check, tags and keywords, attributes, a phone-frame preview of the 상세페이지, and a zip download of every slice for the 스마트에디터.
- Light and dark themes, a mobile layout, and Pretendard served locally. There's no frontend build step: Django templates, one CSS file with the design tokens, and a small amount of vanilla JS.

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
  pivend/assistant/    conversations, chat SSE proxy, /internal API for the agent
  pivend/web/          pages (login, research, drafts), SVG chart geometry, UI template tags
  pivend/web/static/   app.css (design system), chat.js, app.js, icon sprite, Pretendard
agent/
  src/llm.ts           provider setup (cloud + llama.cpp / OpenAI-compatible)
  src/tools.ts         tool definitions (TypeBox schemas) → Django internal API
  src/prompt.ts        system prompt: Korean marketplace SEO rules + honesty rules
  src/chat.ts          one stateless chat turn → UI events
  src/server.ts        HTTP/SSE server
```

## Roadmap

1. **Seller data uploads**: parse 비즈어드바이저 and 쿠팡 광고 report exports (CSV/XLSX), since no API provides traffic or conversion data.
2. **Store connections**: register as a Naver 커머스솔루션 and a Coupang 연동업체, sync products and orders (Celery beat), and publish approved drafts through the Commerce API and WING API.
3. **Rank tracking** from shopping search snapshots, and keyword volume history.
4. Image generation and background removal for product shots.

Bundled third-party assets: [Pretendard](https://github.com/orioncactus/pretendard) (OFL-1.1), icons from [Lucide](https://lucide.dev) (ISC), [marked](https://github.com/markedjs/marked) (MIT) and [DOMPurify](https://github.com/cure53/DOMPurify) (Apache-2.0 / MPL-2.0).
