/**
 * One chat turn: restore the transcript Django sent, run the agent on the new
 * user message, stream UI events, and return the updated transcript.
 * The service keeps no state between requests.
 */

import { Agent, type AgentMessage, type AgentTool, type ThinkingLevel } from "@earendil-works/pi-agent-core";
import type { Api, AssistantMessage, Model, Models } from "@earendil-works/pi-ai";

export type UiEvent =
	| { type: "assistant_start" }
	| { type: "text_delta"; delta: string }
	| { type: "assistant_end"; stopReason: string; errorMessage?: string }
	| { type: "tool_start"; id: string; name: string; args: unknown }
	| { type: "tool_end"; id: string; name: string; isError: boolean; summary: string; images?: string[]; draftUrl?: string }
	| { type: "error"; message: string }
	| { type: "done"; messages: AgentMessage[]; usage: UsageTotals };

export interface UsageTotals {
	input: number;
	output: number;
	cacheRead: number;
	cacheWrite: number;
	cost: number;
}

export interface ChatDeps {
	models: Models;
	model: Model<Api>;
	thinkingLevel: ThinkingLevel;
	/** The user's key for this request; passed to the provider, never stored. */
	apiKey?: string;
	systemPrompt: string;
	tools: (userId: number) => AgentTool<any, any>[];
}

export interface ChatRequest {
	userId: number;
	conversationId?: string;
	messages: AgentMessage[];
	message: string;
}

const TRANSCRIPT_ROLES = new Set(["user", "assistant", "toolResult"]);

/** Keep only LLM messages; the system prompt and tools are rebuilt on every request. */
export function sanitizeHistory(messages: unknown): AgentMessage[] {
	if (!Array.isArray(messages)) return [];
	return messages.filter(
		(m): m is AgentMessage => typeof m === "object" && m !== null && TRANSCRIPT_ROLES.has((m as { role?: string }).role ?? ""),
	);
}

function textOf(result: { content?: { type: string; text?: string }[] } | undefined): string {
	return (result?.content ?? [])
		.filter((c) => c.type === "text")
		.map((c) => c.text ?? "")
		.join("\n");
}

export async function runChat(
	deps: ChatDeps,
	request: ChatRequest,
	emit: (event: UiEvent) => void,
	signal?: AbortSignal,
): Promise<void> {
	const agent = new Agent({
		initialState: {
			systemPrompt: deps.systemPrompt,
			model: deps.model,
			thinkingLevel: deps.thinkingLevel,
			tools: deps.tools(request.userId),
			messages: sanitizeHistory(request.messages),
		},
		streamFn: (model, context, options) => deps.models.streamSimple(model, context, { ...options, apiKey: deps.apiKey }),
		sessionId: request.conversationId,
	});

	const usage: UsageTotals = { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, cost: 0 };

	agent.subscribe((event) => {
		switch (event.type) {
			case "message_start":
				if (event.message.role === "assistant") emit({ type: "assistant_start" });
				break;
			case "message_update":
				if (event.assistantMessageEvent.type === "text_delta") {
					emit({ type: "text_delta", delta: event.assistantMessageEvent.delta });
				}
				break;
			case "message_end":
				if (event.message.role === "assistant") {
					const message = event.message as AssistantMessage;
					usage.input += message.usage.input;
					usage.output += message.usage.output;
					usage.cacheRead += message.usage.cacheRead;
					usage.cacheWrite += message.usage.cacheWrite;
					usage.cost += message.usage.cost.total;
					emit({ type: "assistant_end", stopReason: message.stopReason, errorMessage: message.errorMessage });
				}
				break;
			case "tool_execution_start":
				emit({ type: "tool_start", id: event.toolCallId, name: event.toolName, args: event.args });
				break;
			case "tool_execution_end": {
				const details = (event.result?.details ?? {}) as { images?: string[]; url?: string };
				emit({
					type: "tool_end",
					id: event.toolCallId,
					name: event.toolName,
					isError: event.isError,
					summary: textOf(event.result).slice(0, 300),
					images: Array.isArray(details.images) ? details.images : undefined,
					draftUrl: typeof details.url === "string" ? details.url : undefined,
				});
				break;
			}
		}
	});

	const onAbort = () => agent.abort();
	signal?.addEventListener("abort", onAbort, { once: true });
	try {
		await agent.prompt(request.message);
	} catch (error) {
		emit({ type: "error", message: error instanceof Error ? error.message : String(error) });
	} finally {
		signal?.removeEventListener("abort", onAbort);
	}

	emit({ type: "done", messages: sanitizeHistory(agent.state.messages), usage });
}
