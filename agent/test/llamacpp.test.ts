/**
 * Exercises the real openai-completions code path against a mock llama-server:
 * model discovery, request shape, streamed tool calls and the follow-up turn.
 */

import assert from "node:assert/strict";
import { createServer } from "node:http";
import { after, before, test } from "node:test";
import { HttpBackend } from "../src/backend.ts";
import { runChat, type UiEvent } from "../src/chat.ts";
import { assertPublicUrl, isPublicAddress, type LlmConfig, LlmConfigError, parseLlmRequest, setupLlm } from "../src/llm.ts";
import { createTools } from "../src/tools.ts";
import { listen, startJsonServer } from "./helpers.ts";

const completions: any[] = [];
const authHeaders: (string | undefined)[] = [];
let llama: Awaited<ReturnType<typeof listen<{}>>>;
let backend: Awaited<ReturnType<typeof startJsonServer>>;

function chunk(delta: object, finish: string | null = null) {
	return { id: "c1", object: "chat.completion.chunk", created: 0, model: "qwen3-test", choices: [{ index: 0, delta, finish_reason: finish }] };
}

before(async () => {
	const server = createServer(async (req, res) => {
		if (req.method === "GET" && req.url === "/v1/models") {
			res.writeHead(200, { "Content-Type": "application/json" });
			res.end(JSON.stringify({ object: "list", data: [{ id: "qwen3-test.gguf", object: "model" }] }));
			return;
		}
		const chunks: Buffer[] = [];
		for await (const c of req) chunks.push(c as Buffer);
		const body = JSON.parse(Buffer.concat(chunks).toString("utf8"));
		completions.push(body);
		authHeaders.push(req.headers.authorization);

		const frames =
			completions.length === 1
				? [
						chunk({ role: "assistant", content: null, tool_calls: [{ index: 0, id: "call_1", type: "function", function: { name: "check_title", arguments: "" } }] }),
						chunk({ tool_calls: [{ index: 0, function: { arguments: '{"title":"린넨 원피스 ' } }] }),
						chunk({ tool_calls: [{ index: 0, function: { arguments: '여름 롱"}' } }] }),
						chunk({}, "tool_calls"),
					]
				: [chunk({ role: "assistant", content: "제목이 " }), chunk({ content: "좋습니다." }), chunk({}, "stop")];
		res.writeHead(200, { "Content-Type": "text/event-stream" });
		for (const frame of frames) res.write(`data: ${JSON.stringify(frame)}\n\n`);
		res.write(`data: ${JSON.stringify({ id: "c1", object: "chat.completion.chunk", created: 0, model: "qwen3-test", choices: [], usage: { prompt_tokens: 50, completion_tokens: 10, total_tokens: 60 } })}\n\n`);
		res.end("data: [DONE]\n\n");
	});
	llama = await listen(server, {});
	backend = await startJsonServer(() => [200, { ok: true, issues: [] }]);
});

after(async () => {
	await llama.close();
	await backend.close();
});

test("llama.cpp provider: discovers the model and completes a tool round-trip", async () => {
	const config: LlmConfig = { ...parseLlmRequest({ provider: "llamacpp", base_url: `${llama.url}/v1`, api_key: "user-key" }), maxTokens: 4096 };
	// The mock listens on 127.0.0.1: refused unless private URLs are allowed (self-hosting).
	await assert.rejects(setupLlm(config), LlmConfigError);
	const llm = await setupLlm(config, { allowPrivateUrls: true });
	assert.equal(llm.model.id, "qwen3-test.gguf");

	const http = new HttpBackend(backend.url, "t");
	const events: UiEvent[] = [];
	await runChat(
		{ ...llm, systemPrompt: "system prompt here", tools: (userId) => createTools(http, userId) },
		{ userId: 3, messages: [], message: "제목 점검해줘" },
		(e) => events.push(e),
	);

	const errors = events.filter((e) => e.type === "error" || (e.type === "assistant_end" && e.errorMessage));
	assert.deepEqual(errors, []);

	// Request shape llama-server understands.
	const first = completions[0];
	assert.equal(first.stream, true);
	assert.equal(first.messages[0].role, "system");
	assert.match(first.messages[0].content, /system prompt here/);
	assert.equal(first.max_tokens, 4096);
	assert.equal(first.max_completion_tokens, undefined);
	assert.equal(first.store, undefined);
	assert.equal(first.reasoning_effort, undefined);
	assert.equal(authHeaders[0], "Bearer user-key");
	assert.ok(first.tools.some((t: any) => t.function.name === "render_detail_page"));

	// The streamed arguments were reassembled and sent to the backend.
	assert.deepEqual(backend.requests[0].body, { title: "린넨 원피스 여름 롱" });
	assert.equal(backend.requests[0].path, "/internal/listings/check-title");

	// Second turn carries the tool result back to the model.
	const second = completions[1];
	assert.ok(second.messages.some((m: any) => m.role === "tool" && m.tool_call_id === "call_1"));

	const text = events.filter((e) => e.type === "text_delta").map((e) => (e as { delta: string }).delta).join("");
	assert.equal(text, "제목이 좋습니다.");
});

test("private and internal addresses are refused for user LLM servers", async () => {
	for (const address of ["127.0.0.1", "10.1.2.3", "172.20.0.1", "192.168.0.10", "169.254.169.254", "100.64.0.1", "::1", "fd00::1", "fe80::1", "::ffff:10.0.0.1"]) {
		assert.equal(isPublicAddress(address), false, address);
	}
	assert.equal(isPublicAddress("8.8.8.8"), true);
	assert.equal(isPublicAddress("2606:4700:4700::1111"), true);
	await assert.rejects(assertPublicUrl("http://localhost:8080/v1"), LlmConfigError);
	await assert.rejects(assertPublicUrl("http://[::1]:8080/v1"), LlmConfigError);
	await assert.rejects(assertPublicUrl("ftp://example.com"), LlmConfigError);
	await assertPublicUrl("https://8.8.8.8/v1");
});

test("cloud providers require the user's key", async () => {
	await assert.rejects(setupLlm(parseLlmRequest({ provider: "anthropic" })), /API 키/);
	const llm = await setupLlm(parseLlmRequest({ provider: "openai", api_key: "sk-x" }));
	assert.equal(llm.model.id, "gpt-5.5");
	assert.equal(llm.apiKey, "sk-x");
	await assert.rejects(setupLlm(parseLlmRequest({ provider: "openai", api_key: "sk-x", model: "gpt-nope" })), /알 수 없는/);
});
