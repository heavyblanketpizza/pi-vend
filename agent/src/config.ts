import type { ThinkingLevel } from "@earendil-works/pi-agent-core";

export type ProviderKind = "anthropic" | "openai" | "google" | "llamacpp" | "openai-compatible";

export interface LlmConfig {
	provider: ProviderKind;
	/** Model id. Optional for cloud providers (a default is used) and llama.cpp (read from /v1/models). */
	model?: string;
	/** Override the provider endpoint. Required for openai-compatible; defaults to localhost:8080 for llama.cpp. */
	baseUrl?: string;
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

export interface Config {
	host: string;
	port: number;
	backendUrl: string;
	internalToken: string;
	llm: LlmConfig;
}

const PROVIDERS: ProviderKind[] = ["anthropic", "openai", "google", "llamacpp", "openai-compatible"];
const THINKING: ThinkingLevel[] = ["off", "minimal", "low", "medium", "high", "xhigh", "max"];

function int(value: string | undefined, fallback: number): number {
	const parsed = Number.parseInt(value ?? "", 10);
	return Number.isFinite(parsed) ? parsed : fallback;
}

export function loadConfig(env: NodeJS.ProcessEnv = process.env): Config {
	const provider = (env.LLM_PROVIDER || "anthropic") as ProviderKind;
	if (!PROVIDERS.includes(provider)) {
		throw new Error(`LLM_PROVIDER must be one of: ${PROVIDERS.join(", ")} (got "${provider}")`);
	}
	const local = provider === "llamacpp" || provider === "openai-compatible";
	const reasoning = env.LLM_REASONING === "true";
	const thinking = (env.LLM_THINKING || (local && !reasoning ? "off" : "medium")) as ThinkingLevel;
	if (!THINKING.includes(thinking)) {
		throw new Error(`LLM_THINKING must be one of: ${THINKING.join(", ")}`);
	}
	const internalToken = env.AGENT_INTERNAL_TOKEN || (env.NODE_ENV === "production" ? "" : "dev-internal-token");
	if (!internalToken) throw new Error("AGENT_INTERNAL_TOKEN is required in production");

	return {
		host: env.AGENT_HOST || "127.0.0.1",
		port: int(env.AGENT_PORT, 3001),
		backendUrl: (env.BACKEND_URL || "http://localhost:8000").replace(/\/$/, ""),
		internalToken,
		llm: {
			provider,
			model: env.LLM_MODEL || undefined,
			baseUrl: env.LLM_BASE_URL || undefined,
			thinking,
			contextWindow: int(env.LLM_CONTEXT_WINDOW, 32768),
			maxTokens: int(env.LLM_MAX_TOKENS, 8192),
			reasoning,
			thinkingFormat: env.LLM_THINKING_FORMAT || undefined,
			vision: env.LLM_VISION === "true",
		},
	};
}
