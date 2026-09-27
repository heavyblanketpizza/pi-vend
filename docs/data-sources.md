# Data sources

This is what a Korean seller tool can get from official APIs, and what it can't. It was compiled in September 2026 from Naver's GitHub support forum, the 검색광고 API repository and integrator guides. Check quotas and terms against the official docs before building on them.

## Keyword and market demand (your own API keys, no seller login)

| Source | What you get | Limits |
|---|---|---|
| 네이버 검색광고 API, 키워드도구 (`GET /keywordstool`) | Monthly PC/mobile searches, average clicks, CTR, 경쟁정도 (`compIdx`), ad depth, related keywords | Needs a 검색광고 account. HMAC-SHA256 signed headers. At most 5 hint keywords per call, no spaces. Tiny volumes come back as `"< 10"`. |
| 네이버 데이터랩 검색어 트렌드 (`POST /v1/datalab/search`) | Relative search trend for up to 5 keyword groups | Ratios (100 = peak in the request), not counts |
| 네이버 데이터랩 쇼핑인사이트 (`POST /v1/datalab/shopping/category/keywords`) | Relative shopping click trend within a category, splittable by device, gender and age | Data from 2017-08-01. Needs a category cid. |
| 네이버 검색 API, 쇼핑 (`GET /v1/search/shop.json`) | Top listings (title, price, mall, brand, category path) and the total listing count | Up to 100 per call, `start` ≤ 1000. Relevance order, not the shopper's personalized ranking. |
| Coupang | No public search-volume or keyword API | The Partners API search allows 10 calls/hour with 10 results, which is useless for research |

## The seller's own store (requires the seller's authorization)

| API | What you get | Access rules |
|---|---|---|
| 네이버 커머스API | Products (create/update, image upload, category attributes), orders (with an `inflowPath` field for Naver-origin orders), settlements, inquiries | A SaaS must register as a 커머스솔루션 (reviewed, listed in 커머스솔루션마켓) or an API 대행사, then obtain per-seller tokens. Collecting a seller's own "내스토어 애플리케이션" credentials to run a service is prohibited. Token-bucket rate limits (HTTP 429). Caller IPs must be registered (max 3). |
| 쿠팡 WING Open API | Products, orders/shipping, returns, CS inquiries, settlement, Rocket Growth | The seller issues a key and selects your company as 연동업체 (or 자체개발 with an IP list, max 10). Keys expire after 180 days. Brand, product identifiers and purchase options have been mandatory since 2026-05-21. HMAC signed. |
| 11번가, G마켓·옥션 (ESM) | Listing and order APIs | Later phase |

## Not available through official APIs

- **Store traffic and conversion** (비즈어드바이저: 유입 키워드, visits, conversion). This isn't in the Commerce API; the only statistics API mentioned on Naver's forum is paid and limited to brand stores. Workaround: sellers upload their exports.
- **Coupang ad reports.** No public seller ads API was found; reports are Excel downloads from the ads center. Workaround: uploads.
- **Real search rank, review counts and sales estimates.** Third-party tools scrape these, which breaks both marketplaces' terms.

## References

- [External SaaS integration rules (Naver Commerce API forum)](https://github.com/commerce-api-naver/commerce-api/discussions/3463)
- [Commerce API rate limits](https://github.com/commerce-api-naver/commerce-api/discussions/6)
- [inflowPath and statistics API thread](https://github.com/commerce-api-naver/commerce-api/discussions/1870)
- [Naver 검색광고 API docs](https://github.com/naver/searchad-apidoc)
- [Naver Open API list](https://github.com/naver/naver-openapi-guide/blob/master/ko/apilist.md)
- [Coupang Open API](https://developers.coupangcorp.com/hc/en-us)
