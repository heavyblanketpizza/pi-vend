export interface Config {
	host: string;
	port: number;
	backendUrl: string;
	internalToken: string;
	/** Let users point the agent at private/loopback LLM servers (single-tenant self-hosting only). */
	allowPrivateLlmUrls: boolean;
}

function int(value: string | undefined, fallback: number): number {
	const parsed = Number.parseInt(value ?? "", 10);
	return Number.isFinite(parsed) ? parsed : fallback;
}

export function loadConfig(env: NodeJS.ProcessEnv = process.env): Config {
	const internalToken = env.AGENT_INTERNAL_TOKEN || (env.NODE_ENV === "production" ? "" : "dev-internal-token");
	if (!internalToken) throw new Error("AGENT_INTERNAL_TOKEN is required in production");

	return {
		host: env.AGENT_HOST || "127.0.0.1",
		port: int(env.AGENT_PORT, 3001),
		backendUrl: (env.BACKEND_URL || "http://localhost:8000").replace(/\/$/, ""),
		internalToken,
		allowPrivateLlmUrls: env.ALLOW_PRIVATE_LLM_URLS === "true" || env.ALLOW_PRIVATE_LLM_URLS === "1",
	};
}
