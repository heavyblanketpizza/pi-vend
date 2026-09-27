/**
 * HTTP entry point. Only Django talks to this service:
 *   GET  /health     -> liveness
 *   GET  /v1/models  -> known model ids per cloud provider
 *   POST /v1/test    -> check a user's model settings with a tiny request
 *   POST /v1/chat    -> Server-Sent Events stream of UiEvents, ending with "done"
 *
 * Model settings (and the user's API key) arrive with every request and are
 * dropped when it ends.
 */

import { timingSafeEqual } from "node:crypto";
import { createServer, type IncomingMessage, type Server, type ServerResponse } from "node:http";
import { pathToFileURL } from "node:url";
import type { AgentTool } from "@earendil-works/pi-agent-core";
import { HttpBackend } from "./backend.ts";
import { runChat, type UiEvent } from "./chat.ts";
import { loadConfig } from "./config.ts";
import { type LlmConfig, LlmConfigError, type LlmSetup, modelCatalog, parseLlmRequest, setupLlm } from "./llm.ts";
import { SYSTEM_PROMPT } from "./prompt.ts";
import { createTools } from "./tools.ts";

const MAX_BODY_BYTES = 10 * 1024 * 1024;

function authorized(req: IncomingMessage, token: string): boolean {
	const expected = Buffer.from(`Bearer ${token}`);
	const actual = Buffer.from(req.headers.authorization ?? "");
	return actual.length === expected.length && timingSafeEqual(actual, expected);
}

function sendJson(res: ServerResponse, status: number, body: unknown): void {
	res.writeHead(status, { "Content-Type": "application/json" });
	res.end(JSON.stringify(body));
}

async function readJson(req: IncomingMessage): Promise<any> {
	const chunks: Buffer[] = [];
	let size = 0;
	for await (const chunk of req) {
		size += chunk.length;
		if (size > MAX_BODY_BYTES) throw new Error("request body too large");
		chunks.push(chunk as Buffer);
	}
	return JSON.parse(Buffer.concat(chunks).toString("utf8") || "{}");
}

export interface AppOptions {
	token: string;
	systemPrompt: string;
	tools: (userId: number) => AgentTool<any, any>[];
	/** Build the model for one request from the user's settings. */
	resolveLlm: (config: LlmConfig) => Promise<LlmSetup>;
	catalog?: () => Record<string, string[]>;
}

function errorMessage(error: unknown): string {
	return error instanceof Error ? error.message : String(error);
}

export function createApp({ token, systemPrompt, tools, resolveLlm, catalog = modelCatalog }: AppOptions): Server {
	return createServer(async (req, res) => {
		const url = new URL(req.url ?? "/", "http://localhost");
		if (!authorized(req, token)) return sendJson(res, 401, { error: "unauthorized" });

		if (req.method === "GET" && url.pathname === "/health") {
			return sendJson(res, 200, { ok: true });
		}

		if (req.method === "GET" && url.pathname === "/v1/models") {
			return sendJson(res, 200, { providers: catalog() });
		}

		if (req.method !== "POST" || (url.pathname !== "/v1/chat" && url.pathname !== "/v1/test")) {
			return sendJson(res, 404, { error: "not found" });
		}

		let body: any;
		try {
			body = await readJson(req);
		} catch (error) {
			return sendJson(res, 400, { error: errorMessage(error) });
		}
		let llm: LlmSetup;
		try {
			llm = await resolveLlm(parseLlmRequest(body.llm));
		} catch (error) {
			const status = error instanceof LlmConfigError ? 400 : 500;
			return sendJson(res, status, { ok: false, error: errorMessage(error), code: "llm_config" });
		}

		if (url.pathname === "/v1/test") {
			// A one-word reply proves the key, model and endpoint all work.
			try {
				const reply = await llm.models.completeSimple(
					llm.model,
					{ messages: [{ role: "user", content: "Reply with the single word OK.", timestamp: Date.now() }] },
					{ apiKey: llm.apiKey, maxTokens: 64, signal: AbortSignal.timeout(60_000) },
				);
				if (reply.stopReason === "error" || reply.stopReason === "aborted") {
					return sendJson(res, 200, { ok: false, error: reply.errorMessage ?? "모델 응답 오류" });
				}
				return sendJson(res, 200, { ok: true, provider: llm.model.provider, model: llm.model.id });
			} catch (error) {
				return sendJson(res, 200, { ok: false, error: errorMessage(error) });
			}
		}

		if (!Number.isInteger(body.user_id) || typeof body.message !== "string" || !body.message.trim()) {
			return sendJson(res, 400, { error: "user_id (integer) and message (string) are required" });
		}

		res.writeHead(200, {
			"Content-Type": "text/event-stream; charset=utf-8",
			"Cache-Control": "no-cache",
			Connection: "keep-alive",
		});
		const abort = new AbortController();
		res.on("close", () => {
			if (!res.writableFinished) abort.abort();
		});
		const emit = (event: UiEvent) => {
			if (!res.writableEnded) res.write(`data: ${JSON.stringify(event)}\n\n`);
		};
		// Comment lines keep proxies from closing the stream during long tool calls.
		const keepAlive = setInterval(() => res.write(": ping\n\n"), 15_000);
		try {
			await runChat(
				{ ...llm, systemPrompt, tools },
				{
					userId: body.user_id,
					conversationId: body.conversation_id ? String(body.conversation_id) : undefined,
					messages: body.messages ?? [],
					message: body.message,
				},
				emit,
				abort.signal,
			);
		} finally {
			clearInterval(keepAlive);
			res.end();
		}
	});
}

async function main(): Promise<void> {
	const config = loadConfig();
	const backend = new HttpBackend(config.backendUrl, config.internalToken);
	const server = createApp({
		token: config.internalToken,
		systemPrompt: SYSTEM_PROMPT,
		tools: (userId) => createTools(backend, userId),
		resolveLlm: (llm) => setupLlm(llm, { allowPrivateUrls: config.allowPrivateLlmUrls }),
	});
	server.listen(config.port, config.host, () => {
		console.log(`pi-vend agent listening on http://${config.host}:${config.port} (backend=${config.backendUrl})`);
	});
	const shutdown = () => server.close(() => process.exit(0));
	process.on("SIGTERM", shutdown);
	process.on("SIGINT", shutdown);
}
if (import.meta.url === pathToFileURL(process.argv[1] ?? "").href) {
	main().catch((error) => {
		console.error(error instanceof Error ? error.message : error);
		process.exit(1);
	});
}
