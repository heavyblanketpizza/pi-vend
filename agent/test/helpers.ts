import { createServer, type IncomingMessage, type Server } from "node:http";
import type { AddressInfo } from "node:net";

export interface RecordedRequest {
	method: string;
	path: string;
	headers: IncomingMessage["headers"];
	body: any;
}

/** Start an HTTP server on a random port; the handler returns [status, json]. */
export async function startJsonServer(
	handler: (req: RecordedRequest) => [number, unknown] | Promise<[number, unknown]>,
): Promise<{ url: string; requests: RecordedRequest[]; close: () => Promise<void> }> {
	const requests: RecordedRequest[] = [];
	const server = createServer(async (req, res) => {
		const chunks: Buffer[] = [];
		for await (const chunk of req) chunks.push(chunk as Buffer);
		const raw = Buffer.concat(chunks).toString("utf8");
		const recorded = { method: req.method ?? "", path: req.url ?? "", headers: req.headers, body: raw ? JSON.parse(raw) : undefined };
		requests.push(recorded);
		const [status, body] = await handler(recorded);
		res.writeHead(status, { "Content-Type": "application/json" });
		res.end(JSON.stringify(body));
	});
	return listen(server, { requests });
}

export async function listen<T>(server: Server, extra: T): Promise<{ url: string; close: () => Promise<void> } & T> {
	await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
	const { port } = server.address() as AddressInfo;
	return {
		...extra,
		url: `http://127.0.0.1:${port}`,
		close: () => new Promise<void>((resolve) => server.close(() => resolve())),
	};
}

/** Parse "data: {...}" SSE frames from a full response body. */
export function parseSse(text: string): any[] {
	return text
		.split("\n\n")
		.map((frame) => frame.split("\n").find((line) => line.startsWith("data: ")))
		.filter((line): line is string => Boolean(line))
		.map((line) => JSON.parse(line.slice(6)));
}
