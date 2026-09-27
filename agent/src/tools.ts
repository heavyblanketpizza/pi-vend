/**
 * The agent's tools. Each one is a thin, typed wrapper over a Django internal
 * endpoint: marketplace credentials and data never live in this process.
 */

import type { AgentTool, AgentToolResult } from "@earendil-works/pi-agent-core";
import { type Static, type TSchema, Type } from "@earendil-works/pi-ai";
import type { Backend } from "./backend.ts";

function stringEnum<const T extends readonly string[]>(values: T, description?: string) {
	return Type.Unsafe<T[number]>({ type: "string", enum: [...values], ...(description ? { description } : {}) });
}

function json(data: unknown, details: Record<string, unknown> = {}): AgentToolResult<Record<string, unknown>> {
	return { content: [{ type: "text", text: JSON.stringify(data) }], details };
}

function tool<P extends TSchema>(
	definition: Omit<AgentTool<P, Record<string, unknown>>, "execute">,
	execute: (params: Static<P>, signal?: AbortSignal) => Promise<AgentToolResult<Record<string, unknown>>>,
): AgentTool<P, Record<string, unknown>> {
	return { ...definition, execute: (_id, params, signal) => execute(params, signal) };
}

const Marketplace = stringEnum(["naver", "coupang"] as const, "Target marketplace");

export const SECTION_TYPES = [
	"hero",
	"problem",
	"benefits",
	"feature",
	"specs",
	"howto",
	"trust",
	"faq",
	"notice",
	"text",
] as const;

const Section = Type.Object(
	{
		type: stringEnum(SECTION_TYPES),
		eyebrow: Type.Optional(Type.String()),
		headline: Type.Optional(Type.String()),
		subheadline: Type.Optional(Type.String()),
		body: Type.Optional(Type.String()),
		caption: Type.Optional(Type.String()),
		image_url: Type.Optional(Type.String({ description: "Public https URL of a product image the seller provided" })),
		badges: Type.Optional(Type.Array(Type.String())),
		points: Type.Optional(Type.Array(Type.String())),
		steps: Type.Optional(Type.Array(Type.String())),
		items: Type.Optional(
			Type.Array(
				Type.Object({
					title: Type.Optional(Type.String()),
					body: Type.Optional(Type.String()),
					icon: Type.Optional(Type.String({ description: "A single emoji" })),
					q: Type.Optional(Type.String()),
					a: Type.Optional(Type.String()),
				}),
			),
		),
		rows: Type.Optional(Type.Array(Type.Object({ label: Type.String(), value: Type.String() }))),
	},
	{ description: "One section of the detail page" },
);

const DETAIL_PAGE_HELP = `Section types and their fields (* = required):
- hero: headline*, eyebrow, subheadline, badges[], image_url — the opening hook
- problem: headline*, points*[] — pain points the product solves
- benefits: headline*, items*[{title*, body, icon}] — key selling points
- feature: headline*, body, image_url, caption — one feature in depth
- specs: headline, rows*[{label*, value*}] — spec table, seller-provided facts only
- howto: headline*, steps*[] — usage or care steps
- trust: headline*, items*[{title*, body}] — certifications/guarantees the seller supplied
- faq: headline, items*[{q*, a*}]
- notice: headline*, body* — shipping / exchange / return info
- text: headline, body*
Use "\\n" for line breaks. Theme colors are optional #RRGGBB values.`;

export function createTools(backend: Backend, userId: number): AgentTool<any, Record<string, unknown>>[] {
	const post = (path: string, body: unknown, signal?: AbortSignal) => backend.post<any>(userId, path, body, signal);
	const get = (path: string, signal?: AbortSignal) => backend.get<any>(userId, path, signal);

	return [
		tool(
			{
				name: "keyword_stats",
				label: "Keyword volume",
				description:
					"Monthly Naver search volume (PC/mobile), clicks, CTR and ad competition for up to 20 keywords, from the Naver 검색광고 keyword tool. " +
					"Set with_competition to also get the Naver Shopping listing count and competition_ratio (listings per monthly search; lower = less crowded). " +
					"Naver data is the best available proxy for Coupang demand too.",
				parameters: Type.Object({
					keywords: Type.Array(Type.String(), { minItems: 1, maxItems: 20 }),
					with_competition: Type.Optional(Type.Boolean({ description: "Adds one shopping search call per keyword" })),
				}),
			},
			async (p, signal) => json(await post("research/keyword-stats", p, signal)),
		),
		tool(
			{
				name: "related_keywords",
				label: "Related keywords",
				description:
					"Related keywords for a seed keyword with monthly search volume, sorted by volume (Naver 검색광고 keyword tool). " +
					"Use it to find long-tail variants before picking target keywords.",
				parameters: Type.Object({
					seed: Type.String(),
					limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 200, default: 40 })),
					min_searches: Type.Optional(Type.Integer({ minimum: 0, description: "Drop keywords below this monthly volume" })),
				}),
			},
			async (p, signal) => json(await post("research/related-keywords", { limit: 40, ...p }, signal)),
		),
		tool(
			{
				name: "keyword_trend",
				label: "Keyword trend",
				description:
					"Relative search trend (Naver 데이터랩) for up to 5 keywords: seasonality, peaks, recent change. " +
					"Pass a top-level 네이버쇼핑 category (e.g. 패션의류, 식품, 생활/건강) to get shopping click trends within that category instead. " +
					"Values are ratios where 100 is the peak across the request, not absolute counts.",
				parameters: Type.Object({
					keywords: Type.Array(Type.String(), { minItems: 1, maxItems: 5 }),
					months: Type.Optional(Type.Integer({ minimum: 1, maximum: 60, default: 12 })),
					time_unit: Type.Optional(stringEnum(["date", "week", "month"] as const)),
					category: Type.Optional(Type.String({ description: "Top-level category name or cid" })),
					device: Type.Optional(stringEnum(["pc", "mo"] as const)),
					gender: Type.Optional(stringEnum(["m", "f"] as const)),
				}),
			},
			async (p, signal) => json(await post("research/trend", p, signal)),
		),
		tool(
			{
				name: "analyze_competitors",
				label: "Competitor analysis",
				description:
					"Analyze the top Naver Shopping listings for a query: total listing count, price distribution, most-used title words, " +
					"dominant categories, top malls/brands and the top 10 titles. Order is Naver's relevance sort, not a shopper's personalized ranking.",
				parameters: Type.Object({
					query: Type.String(),
					sample: Type.Optional(Type.Integer({ minimum: 10, maximum: 100, default: 40 })),
				}),
			},
			async (p, signal) => json(await post("research/competitors", p, signal)),
		),
		tool(
			{
				name: "check_title",
				label: "Check title",
				description:
					"Check a product title (상품명) against common marketplace guidance: length, repeated words, promotional terms, " +
					"decorative symbols, target keyword coverage and brand placement. Run it on every title you propose.",
				parameters: Type.Object({
					title: Type.String(),
					marketplace: Type.Optional(Marketplace),
					target_keywords: Type.Optional(Type.Array(Type.String())),
					brand: Type.Optional(Type.String()),
				}),
			},
			async (p, signal) => json(await post("listings/check-title", p, signal)),
		),
		tool(
			{
				name: "list_drafts",
				label: "List drafts",
				description: "List the seller's saved listing drafts (id, product, title, status).",
				parameters: Type.Object({}),
			},
			async (_p, signal) => json(await get("listings/drafts", signal)),
		),
		tool(
			{
				name: "get_draft",
				label: "Get draft",
				description: "Load one listing draft with all fields, its detail page spec and latest render.",
				parameters: Type.Object({ draft_id: Type.Integer() }),
			},
			async (p, signal) => {
				const draft = await get(`listings/drafts/${p.draft_id}`, signal);
				return json(draft, { url: draft.url });
			},
		),
		tool(
			{
				name: "save_draft",
				label: "Save draft",
				description:
					"Create a listing draft (omit id; product_name required) or update fields of an existing one (pass id). " +
					"Only fields you pass are changed. Nothing is published to a marketplace; the seller reviews and approves drafts in the app.",
				parameters: Type.Object({
					id: Type.Optional(Type.Integer()),
					product_name: Type.Optional(Type.String({ description: "Internal product name" })),
					marketplace: Type.Optional(Marketplace),
					title: Type.Optional(Type.String({ description: "상품명 to list with" })),
					tags: Type.Optional(Type.Array(Type.String(), { maxItems: 10, description: "Search tags (스마트스토어 allows up to 10)" })),
					target_keywords: Type.Optional(Type.Array(Type.String())),
					category_path: Type.Optional(Type.String({ description: "e.g. 패션의류 > 여성의류 > 원피스" })),
					attributes: Type.Optional(
						Type.Array(Type.Object({ name: Type.String(), value: Type.String() }), {
							description: "Product attributes, e.g. {name: 소재, value: 린넨 55%}",
						}),
					),
					notes: Type.Optional(Type.String({ description: "Rationale, open questions, facts to confirm" })),
				}),
			},
			async ({ attributes, ...rest }, signal) => {
				const body = attributes ? { ...rest, attributes: Object.fromEntries(attributes.map((a) => [a.name, a.value])) } : rest;
				const draft = await post("listings/drafts", body, signal);
				return json(draft, { url: draft.url });
			},
		),
		tool(
			{
				name: "render_detail_page",
				label: "Render detail page",
				description:
					"Write and render a draft's 상세페이지 (860px wide, sliced into JPG images). Saves the spec on the draft and returns image URLs " +
					"plus the draft page link to share with the seller. If validation fails, fix the listed fields and call again.\n" +
					DETAIL_PAGE_HELP,
				parameters: Type.Object({
					draft_id: Type.Integer(),
					detail_page: Type.Object({
						theme: Type.Optional(
							Type.Object({
								accent: Type.Optional(Type.String()),
								background: Type.Optional(Type.String()),
								text: Type.Optional(Type.String()),
								muted: Type.Optional(Type.String()),
								surface: Type.Optional(Type.String()),
							}),
						),
						sections: Type.Array(Section, { minItems: 1, maxItems: 20 }),
					}),
				}),
			},
			async (p, signal) => {
				const result = await post(`listings/drafts/${p.draft_id}/render`, { detail_page: p.detail_page }, signal);
				return json(result, { images: result.images, url: result.draft_url });
			},
		),
	];
}
