/**
 * LLM wiring. One provider is active per process, chosen by LLM_PROVIDER:
 *
 *   anthropic          Claude via ANTHROPIC_API_KEY
 *   openai             OpenAI via OPENAI_API_KEY
 *   google             Gemini via GEMINI_API_KEY
 *   llamacpp           a local llama-server (OpenAI-compatible, no key)
 *   openai-compatible  any other OpenAI-compatible server (vLLM, LM Studio, Ollama...), LLM_API_KEY optional
 */

import {
	type Api,
	clampThinkingLevel,
	createModels,
	createProvider,
	envApiKeyAuth,
	type Model,
	type Models,
	type OpenAICompletionsCompat,
} from "@earendil-works/pi-ai";
import { openAICompletionsApi } from "@earendil-works/pi-ai/api/openai-completions.lazy";
import { anthropicProvider } from "@earendil-works/pi-ai/providers/anthropic";
import { googleProvider } from "@earendil-works/pi-ai/providers/google";
import { openaiProvider } from "@earendil-works/pi-ai/providers/openai";
import type { ThinkingLevel } from "@earendil-works/pi-agent-core";
import type { LlmConfig } from "./config.ts";

export const DEFAULT_MODELS = {
	anthropic: "claude-opus-5",
	openai: "gpt-5.5",
	google: "gemini-3.5-flash",
} as const;

const KEY_ENV = {
	anthropic: "ANTHROPIC_API_KEY",
	openai: "OPENAI_API_KEY",
	google: "GEMINI_API_KEY",
} as const;

export interface LlmSetup {
	models: Models;
	model: Model<Api>;
	thinkingLevel: ThinkingLevel;
}

async function cloudSetup(config: LlmConfig & { provider: "anthropic" | "openai" | "google" }): Promise<LlmSetup> {
	const models = createModels();
	const factory = { anthropic: anthropicProvider, openai: openaiProvider, google: googleProvider }[config.provider];
	models.setProvider(factory());

	const id = config.model ?? DEFAULT_MODELS[config.provider];
	const found = models.getModel(config.provider, id);
	if (!found) {
		const known = models.getModels(config.provider).map((m) => m.id);
		throw new Error(`Unknown ${config.provider} model "${id}". Known models: ${known.join(", ")}`);
	}
	if (!(await models.getAuth(config.provider))) {
		throw new Error(`${config.provider} is not configured: set ${KEY_ENV[config.provider]}`);
	}
	const model = config.baseUrl ? { ...found, baseUrl: config.baseUrl } : found;
	return { models, model, thinkingLevel: clampThinkingLevel(model, config.thinking) };
}

/** llama-server (and most OpenAI-compatible servers) list the loaded model at GET /models. */
async function discoverModelId(baseUrl: string, apiKey?: string): Promise<string> {
	const response = await fetch(`${baseUrl}/models`, {
		headers: apiKey ? { Authorization: `Bearer ${apiKey}` } : {},
		signal: AbortSignal.timeout(5000),
	});
	if (!response.ok) throw new Error(`GET ${baseUrl}/models returned ${response.status}`);
	const body = (await response.json()) as { data?: { id?: string }[] };
	const id = body.data?.[0]?.id;
	if (!id) throw new Error(`No models listed at ${baseUrl}/models; set LLM_MODEL`);
	return id;
}

export function localModel(config: LlmConfig, id: string, baseUrl: string): Model<"openai-completions"> {
	const compat: OpenAICompletionsCompat = {
		// llama.cpp and friends expect a plain system message and max_tokens.
		supportsDeveloperRole: false,
		supportsReasoningEffort: false,
		supportsStore: false,
		maxTokensField: "max_tokens",
	};
	if (config.thinkingFormat) {
		compat.thinkingFormat = config.thinkingFormat as OpenAICompletionsCompat["thinkingFormat"];
	}
	return {
		id,
		name: id,
		api: "openai-completions",
		provider: config.provider,
		baseUrl,
		reasoning: config.reasoning,
		input: config.vision ? ["text", "image"] : ["text"],
		cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
		contextWindow: config.contextWindow,
		maxTokens: config.maxTokens,
		compat,
	};
}

async function localSetup(config: LlmConfig): Promise<LlmSetup> {
	const baseUrl = (config.baseUrl ?? (config.provider === "llamacpp" ? "http://localhost:8080/v1" : "")).replace(/\/$/, "");
	if (!baseUrl) throw new Error("LLM_BASE_URL is required for openai-compatible");
	const apiKey = process.env.LLM_API_KEY || undefined;
	const id = config.model ?? (await discoverModelId(baseUrl, apiKey));
	const model = localModel(config, id, baseUrl);

	const models = createModels();
	models.setProvider(
		createProvider({
			id: config.provider,
			baseUrl,
			auth: {
				apiKey: apiKey
					? envApiKeyAuth("OpenAI-compatible API key", ["LLM_API_KEY"])
					: // Keyless local servers still need an auth entry; send a placeholder token.
						{ name: "local server", resolve: async () => ({ auth: { apiKey: "local" } }) },
			},
			models: [model],
			api: openAICompletionsApi(),
		}),
	);
	return { models, model, thinkingLevel: clampThinkingLevel(model, config.thinking) };
}

export async function setupLlm(config: LlmConfig): Promise<LlmSetup> {
	switch (config.provider) {
		case "anthropic":
		case "openai":
		case "google":
			return cloudSetup({ ...config, provider: config.provider });
		case "llamacpp":
		case "openai-compatible":
			return localSetup(config);
	}
}
