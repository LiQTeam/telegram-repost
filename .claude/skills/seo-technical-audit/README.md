# seo-technical-audit

Expert guide for technical SEO auditing.

## Purpose
Teaches Claude how to perform comprehensive technical SEO audits covering crawlability, indexing, Core Web Vitals, page speed, mobile-friendliness, HTTPS, redirects, sitemaps, robots.txt, hreflang, and HTTP status codes.

## Activation Triggers
This skill activates when the user mentions: crawlability, indexing, page speed, Core Web Vitals, LCP, INP, CLS, mobile-friendly, HTTPS, robots.txt, XML sitemap, canonical, hreflang, redirect chain, HTTP status codes, technical SEO, site audit, crawl budget.

## Files
| File | Lines | Description |
|------|-------|-------------|
| SKILL.md | ~300 | Core technical SEO concepts and rules |
| ERROR_CATALOG.md | ~250 | Complete issue catalog by category and severity |
| AUDIT_WORKFLOW.md | ~200 | Step-by-step audit methodology with MCP tools |
| HTTP_STATUS_REFERENCE.md | ~150 | HTTP status codes with SEO implications |

## MCP Tools Used
- `analyze_robots_txt` — robots.txt parsing and validation
- `analyze_sitemap` — XML sitemap analysis
- `analyze_page` — page-level technical checks
- `check_core_web_vitals` — Core Web Vitals and Lighthouse
- `check_mobile_friendly` — mobile usability
- `extract_schema` — structured data validation
- `gsc_index_coverage` — Google Search Console indexing data
- `gsc_sitemaps` — sitemap submission status

## Evaluation Scenarios
1. robots.txt blocking important pages
2. 4-hop redirect chain detected
3. Page with poor Core Web Vitals
4. Multi-language site missing hreflang
5. HTTPS page with mixed content
