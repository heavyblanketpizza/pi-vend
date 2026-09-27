/** Client for the Django internal API (the data plane behind every tool). */

export class BackendError extends Error {
	readonly status: number;
	readonly details?: unknown;
	readonly code?: string;

	constructor(status: number, message: string, details?: unknown, code?: string) {
		super(message);
		this.status = status;
		this.details = details;
		this.code = code;
	}
}

export interface Backend {
	get<T = unknown>(userId: number, path: string, signal?: AbortSignal): Promise<T>;
	post<T = unknown>(userId: number, path: string, body: unknown, signal?: AbortSignal): Promise<T>;
}

export class HttpBackend implements Backend {
	private readonly baseUrl: string;
	private readonly token: string;

	constructor(baseUrl: string, token: string) {
		this.baseUrl = baseUrl;
		this.token = token;
	}

	get<T>(userId: number, path: string, signal?: AbortSignal): Promise<T> {
		return this.request<T>(userId, "GET", path, undefined, signal);
	}

	post<T>(userId: number, path: string, body: unknown, signal?: AbortSignal): Promise<T> {
		return this.request<T>(userId, "POST", path, body, signal);
	}

	private async request<T>(userId: number, method: string, path: string, body: unknown, signal?: AbortSignal): Promise<T> {
		const response = await fetch(`${this.baseUrl}/internal/${path}`, {
			method,
			headers: {
				Authorization: `Bearer ${this.token}`,
				"X-Pivend-User": String(userId),
				"Content-Type": "application/json",
			},
			body: body === undefined ? undefined : JSON.stringify(body),
			signal: signal ? AbortSignal.any([signal, AbortSignal.timeout(120_000)]) : AbortSignal.timeout(120_000),
		});
		const text = await response.text();
		let data: any;
		try {
			data = JSON.parse(text);
		} catch {
			data = { error: text.slice(0, 300) };
		}
		if (!response.ok) {
			const details = data?.details ? ` Details: ${JSON.stringify(data.details)}` : "";
			throw new BackendError(response.status, `${data?.error ?? `HTTP ${response.status}`}${details}`, data?.details, data?.code);
		}
		return data as T;
	}
}
