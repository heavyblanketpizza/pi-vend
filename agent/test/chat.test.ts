import assert from "node:assert/strict";
import { after, before, test } from "node:test";
import { createModels, fauxAssistantMessage, fauxProvider, fauxText, fauxToolCall } from "@earendil-works/pi-ai";
import { HttpBackend } from "../src/backend.ts";
import { runChat, sanitizeHistory, type UiEvent } from "../src/chat.ts";
import { createApp } from "../src/server.ts";
import { createTools } from "../src/tools.ts";
import { listen, parseSse, startJsonServer } from "./helpers.ts";

const TOKEN = "test-token";
let backend: Awaited<ReturnType<typeof startJsonServer>>;

before(async () => {
	backend = await startJsonServer((req) => {
		if (req.path === "/internal/research/keyword-stats") {
			return [200, { keywords: [{ query: "린넨 원피스", found: true, monthly_searches: { total: 12000 } }] }];
		}
		if (req.path === "/internal/listings/drafts/7/render") {
			return [400, { error: "invalid detail page spec", details: ["sections[0].headline is required for 'hero' sections"] }];
		}
		return [404, { error: "not found" }];
	});
});

after(async () => backend.close());

function fauxDeps() {
	const faux = fauxProvider();
	const models = createModels();
	models.setProvider(faux.provider);
	const http = new HttpBackend(backend.url, TOKEN);
	return {
		faux,
		deps: {
			models,
			model: faux.getModel(),
			thinkingLevel: "off" as const,
			systemPrompt: "test prompt",
			tools: (userId: number) => createTools(http, userId),
		},
	};
}

test("runs a tool against the backend and returns the transcript", async () => {
	const { faux, deps } = fauxDeps();
	faux.setResponses([
		fauxAssistantMessage([fauxText("검색량을 볼게요."), fauxToolCall("keyword_stats", { keywords: ["린넨 원피스"] })], {
			stopReason: "toolUse",
		}),
		fauxAssistantMessage([fauxText("월간 12,000회 검색됩니다.")]),
	]);

	const events: UiEvent[] = [];
	await runChat(deps, { userId: 42, messages: [], message: "린넨 원피스 검색량?" }, (e) => events.push(e));

	const call = backend.requests.find((r) => r.path === "/internal/research/keyword-stats");
	assert.ok(call, "backend was called");
	assert.equal(call.headers.authorization, `Bearer ${TOKEN}`);
	assert.equal(call.headers["x-pivend-user"], "42");
	assert.deepEqual(call.body, { keywords: ["린넨 원피스"] });

	const types = events.map((e) => e.type);
	assert.ok(types.includes("tool_start"));
	const toolEnd = events.find((e) => e.type === "tool_end");
	assert.ok(toolEnd && toolEnd.type === "tool_end" && !toolEnd.isError);

	const text = events.filter((e) => e.type === "text_delta").map((e) => (e as { delta: string }).delta).join("");
	assert.match(text, /12,000/);

	const done = events.at(-1);
	assert.ok(done && done.type === "done");
	assert.deepEqual(
		done.messages.map((m) => m.role),
		["user", "assistant", "toolResult", "assistant"],
		"system prompt is not persisted",
	);
});

test("backend validation errors reach the model as tool errors", async () => {
	const { faux, deps } = fauxDeps();
	faux.setResponses([
		fauxAssistantMessage(
			[fauxToolCall("render_detail_page", { draft_id: 7, detail_page: { sections: [{ type: "hero" }] } })],
			{ stopReason: "toolUse" },
		),
		fauxAssistantMessage([fauxText("고쳐서 다시 시도할게요.")]),
	]);

	const events: UiEvent[] = [];
	await runChat(deps, { userId: 1, messages: [], message: "상세페이지 만들어줘" }, (e) => events.push(e));

	const toolEnd = events.find((e) => e.type === "tool_end");
	assert.ok(toolEnd && toolEnd.type === "tool_end");
	assert.equal(toolEnd.isError, true);
	assert.match(toolEnd.summary, /headline is required/);
});

test("history keeps only LLM messages", () => {
	const history = sanitizeHistory([
		{ role: "system", content: "old prompt" },
		{ role: "user", content: "hi", timestamp: 1 },
		"garbage",
		null,
	]);
	assert.deepEqual(history.map((m) => m.role), ["user"]);
});

test("HTTP API requires the token and streams SSE", async () => {
	const { faux, deps } = fauxDeps();
	faux.setResponses([fauxAssistantMessage([fauxText("안녕하세요!")])]);
	const app = await listen(createApp({ token: TOKEN, deps }), {});
	try {
		const denied = await fetch(`${app.url}/health`);
		assert.equal(denied.status, 401);

		const health = (await (await fetch(`${app.url}/health`, { headers: { Authorization: `Bearer ${TOKEN}` } })).json()) as { ok: boolean };
		assert.equal(health.ok, true);

		const bad = await fetch(`${app.url}/v1/chat`, {
			method: "POST",
			headers: { Authorization: `Bearer ${TOKEN}`, "Content-Type": "application/json" },
			body: JSON.stringify({ message: "hi" }),
		});
		assert.equal(bad.status, 400);

		const response = await fetch(`${app.url}/v1/chat`, {
			method: "POST",
			headers: { Authorization: `Bearer ${TOKEN}`, "Content-Type": "application/json" },
			body: JSON.stringify({ user_id: 1, messages: [], message: "안녕" }),
		});
		assert.equal(response.status, 200);
		assert.match(response.headers.get("content-type") ?? "", /text\/event-stream/);
		const events = parseSse(await response.text());
		assert.equal(events.at(-1).type, "done");
		assert.equal(events.at(-1).messages.length, 2);
	} finally {
		await app.close();
	}
});
