/**
 * LLM wiring. Each chat request carries the user's own model settings (sent
 * by Django, key included); nothing is read from this process's environment.
 *
 *   anthropic          Claude, user's API key
 *   openai             OpenAI, user's API key
 *   google             Gemini, user's API key
 *   llamacpp           the user's llama-server (OpenAI-compatible), key optional
 *   openai-compatible  any other OpenAI-compatible server (vLLM, LM Studio, Ollama...), key optional
 */

import { lookup } from "node:dns/promises";
import { isIP } from "node:net";
import {
	type Api,
	clampThinkingLevel,
	createModels,
	createProvider,
	type Model,
	type Models,
	type OpenAICompletionsCompat,
} from "@earendil-works/pi-ai";
import { openAICompletionsApi } from "@earendil-works/pi-ai/api/openai-completions.lazy";
import { anthropicProvider } from "@earendil-works/pi-ai/providers/anthropic";
import { googleProvider } from "@earendil-works/pi-ai/providers/google";
import { openaiProvider } from "@earendil-works/pi-ai/providers/openai";
import type { ThinkingLevel } from "@earendil-works/pi-agent-core";

export type ProviderKind = "anthropic" | "openai" | "google" | "llamacpp" | "openai-compatible";
const CLOUD = ["anthropic", "openai", "google"] as const;
type CloudKind = (typeof CLOUD)[number];
export const PROVIDERS: ProviderKind[] = [...CLOUD, "llamacpp", "openai-compatible"];

export const DEFAULT_MODELS: Record<CloudKind, string> = {
	anthropic: "claude-opus-5",
	openai: "gpt-5.5",
	google: "gemini-3.5-flash",
};

export interface LlmConfig {
	provider: ProviderKind;
	/** Model id. Optional for cloud providers (a default is used) and local servers (read from /models). */
	model?: string;
	/** Server URL. Required for local providers; overrides the endpoint for cloud ones. */
	baseUrl?: string;
	apiKey?: string;
	thinking: ThinkingLevel;
	/** Local models only: context window and output cap to advertise. */
	contextWindow: number;
	maxTokens: number;
	/** Local models only: the model emits reasoning and accepts thinking controls. */
	reasoning: boolean;
	/** Local models only: how to switch thinking on/off, e.g. "qwen-chat-template" for Qwen3 on llama.cpp. */
	thinkingFormat?: string;
	/** Local models only: the model accepts image input. */
	vision: boolean;
}

export interface LlmSetup {
	models: Models;
	model: Model<Api>;
	thinkingLevel: ThinkingLevel;
	/** Sent with every request; never stored. */
	apiKey?: string;
}

export interface LlmOptions {
	/** Allow local-provider URLs that resolve to private/loopback addresses (self-hosting). */
	allowPrivateUrls: boolean;
}

export class LlmConfigError extends Error {}

const str = (v: unknown) => (typeof v === "string" && v.trim() ? v.trim() : undefined);

/** Validate the `llm` object Django sends (snake_case) into an LlmConfig. */
export function parseLlmRequest(raw: unknown): LlmConfig {
	if (!raw || typeof raw !== "object") throw new LlmConfigError("AI 모델이 연결되지 않았어요. 설정 > API 연결에서 모델을 등록해 주세요.");
	const body = raw as Record<string, unknown>;
	const provider = body.provider as ProviderKind;
	if (!PROVIDERS.includes(provider)) throw new LlmConfigError(`지원하지 않는 AI 제공자예요: ${String(body.provider)}`);
	const local = provider === "llamacpp" || provider === "openai-compatible";
	const reasoning = body.reasoning === true;
	return {
		provider,
		model: str(body.model),
		baseUrl: str(body.base_url),
		apiKey: str(body.api_key),
		thinking: local && !reasoning ? "off" : "medium",
		contextWindow: 32768,
		maxTokens: 8192,
		reasoning,
		thinkingFormat: str(body.thinking_format),
		vision: false,
	};
}

// One shared registry for the cloud catalogs; keys are supplied per request.
let cloudModels: Models | undefined;
function cloudRegistry(): Models {
	if (!cloudModels) {
		const models = createModels();
		models.setProvider(anthropicProvider());
		models.setProvider(openaiProvider());
		models.setProvider(googleProvider());
		cloudModels = models;
	}
	return cloudModels;
}

/** Known model ids per cloud provider (for the settings page). */
export function modelCatalog(): Record<CloudKind, string[]> {
	const models = cloudRegistry();
	return Object.fromEntries(CLOUD.map((p) => [p, models.getModels(p).map((m) => m.id)])) as Record<CloudKind, string[]>;
}

function cloudSetup(config: LlmConfig & { provider: CloudKind }): LlmSetup {
	if (!config.apiKey) throw new LlmConfigError(`${config.provider} API 키가 없어요.`);
	const models = cloudRegistry();
	const id = config.model ?? DEFAULT_MODELS[config.provider];
	const found = models.getModel(config.provider, id);
	if (!found) {
		const known = models.getModels(config.provider).map((m) => m.id);
		throw new LlmConfigError(`알 수 없는 ${config.provider} 모델이에요: "${id}". 사용 가능: ${known.slice(-8).join(", ")}`);
	}
	return { models, model: found, thinkingLevel: clampThinkingLevel(found, config.thinking), apiKey: config.apiKey };
}

/** Refuse URLs that resolve to loopback/private/link-local addresses (SSRF). */
export async function assertPublicUrl(url: string): Promise<void> {
	let parsed: URL;
	try {
		parsed = new URL(url);
	} catch {
		throw new LlmConfigError("서버 주소 형식이 올바르지 않아요.");
	}
	if (!["http:", "https:"].includes(parsed.protocol)) throw new LlmConfigError("http(s) 주소만 사용할 수 있어요.");
	const host = parsed.hostname.replace(/^\[|\]$/g, "");
	if (!host || host === "localhost" || host.endsWith(".localhost")) throw new LlmConfigError("내부 주소는 사용할 수 없어요.");
	const addresses = isIP(host) ? [{ address: host }] : await lookup(host, { all: true }).catch(() => []);
	if (addresses.length === 0) throw new LlmConfigError(`서버 주소를 찾을 수 없어요: ${host}`);
	if (addresses.some((a) => !isPublicAddress(a.address))) throw new LlmConfigError("내부·사설 IP 주소는 사용할 수 없어요.");
}

export function isPublicAddress(address: string): boolean {
	const v4 = address.startsWith("::ffff:") ? address.slice(7) : address;
	if (isIP(v4) === 4) {
		const [a, b] = v4.split(".").map(Number);
		return !(
			a === 0 || a === 10 || a === 127 || a >= 224 ||
			(a === 100 && b >= 64 && b <= 127) || (a === 169 && b === 254) ||
			(a === 172 && b >= 16 && b <= 31) || (a === 192 && b === 168) ||
			(a === 198 && (b === 18 || b === 19))
		);
	}
	const lower = address.toLowerCase();
	return !(lower === "::" || lower === "::1" || /^f[cd]/.test(lower) || /^fe[89ab]/.test(lower) || lower.startsWith("ff"));
}

// Discovered model ids per server, so each chat turn doesn't re-query /models.
const discovered = new Map<string, { id: string; at: number }>();
const DISCOVERY_TTL_MS = 60_000;

/** llama-server (and most OpenAI-compatible servers) list the loaded model at GET /models. */
async function discoverModelId(baseUrl: string, apiKey?: string): Promise<string> {
	const cached = discovered.get(baseUrl);
	if (cached && Date.now() - cached.at < DISCOVERY_TTL_MS) return cached.id;
	let response: Response;
	try {
		response = await fetch(`${baseUrl}/models`, {
			headers: apiKey ? { Authorization: `Bearer ${apiKey}` } : {},
			signal: AbortSignal.timeout(5000),
			redirect: "error",
		});
	} catch (error) {
		throw new LlmConfigError(`${baseUrl}/models 에 연결할 수 없어요 (${error instanceof Error ? error.message : error}).`);
	}
	if (!response.ok) throw new LlmConfigError(`${baseUrl}/models 응답 오류 (HTTP ${response.status}). 모델 ID를 직접 입력해 보세요.`);
	const body = (await response.json().catch(() => ({}))) as { data?: { id?: string }[] };
	const id = body.data?.[0]?.id;
	if (!id) throw new LlmConfigError(`${baseUrl}/models 에 모델이 없어요. 모델 ID를 직접 입력해 주세요.`);
	discovered.set(baseUrl, { id, at: Date.now() });
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

async function localSetup(config: LlmConfig, options: LlmOptions): Promise<LlmSetup> {
	const baseUrl = (config.baseUrl ?? "").replace(/\/$/, "");
	if (!baseUrl) throw new LlmConfigError("서버 주소가 필요해요.");
	if (!options.allowPrivateUrls) await assertPublicUrl(baseUrl);
	const id = config.model ?? (await discoverModelId(baseUrl, config.apiKey));
	const model = localModel(config, id, baseUrl);
	const apiKey = config.apiKey ?? "local"; // keyless servers still get a placeholder token

	const models = createModels();
	models.setProvider(
		createProvider({
			id: config.provider,
			baseUrl,
			auth: { apiKey: { name: "user key", resolve: async () => ({ auth: { apiKey } }) } },
			models: [model],
			api: openAICompletionsApi(),
		}),
	);
	return { models, model, thinkingLevel: clampThinkingLevel(model, config.thinking), apiKey };
}

export async function setupLlm(config: LlmConfig, options: LlmOptions = { allowPrivateUrls: false }): Promise<LlmSetup> {
	switch (config.provider) {
		case "anthropic":
		case "openai":
		case "google":
			return cloudSetup({ ...config, provider: config.provider });
		case "llamacpp":
		case "openai-compatible":
			return localSetup(config, options);
	}
}
