# Complete SEO Audit Workflow Guide

Step-by-step guide for running a comprehensive SEO audit using seo-mcp tools.

---

## Decision Tree: Which Tools to Run

```
User provides a URL or domain
│
├── Single page analysis?
│   └── Run: Full Page Audit workflow
│
├── Entire site audit?
│   └── Run: Technical Site Audit workflow
│
├── Content optimization?
│   └── Run: Content Optimization workflow
│
├── Competitive analysis?
│   └── Run: Competitive Analysis workflow
│
└── Schema implementation?
    └── Run: Schema Implementation workflow
```

---

## Full Page Audit (Most Common)

**When:** User provides a single URL and wants an SEO analysis.

### Phase 1: Quick scan (always run)
```
analyze_page(url, { includeContent: true, followRedirects: true })
```
→ Get the overall picture. Review the score and identify major issues.

### Phase 2: Deep dive (based on Phase 1 findings)

**If heading issues found:**
```
analyze_headings(url, { targetKeyword: "..." })
```

**If image issues found:**
```
analyze_images(url, { checkFileSize: true })
```

**If link issues found:**
```
analyze_internal_links(url, { checkBrokenLinks: true })
```

**If structured data needed/present:**
```
extract_schema(url, { validateGoogle: true })
```

### Phase 3: Performance (always run for thorough audit)
```
check_core_web_vitals(url, { strategy: "mobile" })
```

### Phase 4: Suggestions (always run)
```
generate_meta_suggestions(url, { targetKeyword: "..." })
```

### Reporting order
1. Overall score and summary
2. Critical issues (fix immediately)
3. High priority issues
4. Performance metrics
5. Improvement suggestions
6. Recommended next steps

---

## Technical Site Audit

**When:** User wants to audit the entire site's SEO health.

### Phase 1: Foundation
```
analyze_robots_txt(domain)
analyze_sitemap(domain)
```
→ Check if search engines can access and discover pages.

### Phase 2: Key pages
Run `analyze_page` on:
1. Homepage
2. 3-5 top landing pages
3. 1-2 category pages
4. 1-2 individual content/product pages

### Phase 3: Performance
```
check_core_web_vitals(homepage, { strategy: "mobile" })
check_core_web_vitals(slowestPage, { strategy: "mobile" })
check_mobile_friendly(homepage)
```

### Phase 4: Search Console (if available)
```
gsc_index_coverage(siteUrl)
gsc_performance(siteUrl, { dimensions: ["page"], rowLimit: 20 })
gsc_sitemaps(siteUrl)
```

---

## Progressive Analysis Strategy

Don't run all tools at once. Use a progressive approach:

### Level 1: Quick check (1-2 tools, 5-10 seconds)
- `analyze_page` gives 80% of what you need
- Good for quick questions or initial assessment

### Level 2: Standard audit (4-5 tools, 30-60 seconds)
- `analyze_page` + `check_core_web_vitals` + `extract_schema` + `generate_meta_suggestions`
- Covers on-page + performance + structured data + actionable suggestions

### Level 3: Comprehensive audit (8-10 tools, 2-5 minutes)
- All analysis tools + performance tools + generation tools
- For thorough professional-grade audits

### Level 4: Full competitive analysis (12+ tool calls, 5-10 minutes)
- Level 3 + research tools (keywords, SERP, backlinks) + competitor page analysis
- Requires API keys for research tools

---

## Handling Tool Failures

### API key not configured
```
Error: DataForSEO API key not configured
```
**Response:** Inform the user that keyword/SERP/backlink tools require a DataForSEO API key. Suggest they configure `DATAFORSEO_LOGIN` and `DATAFORSEO_PASSWORD` in their environment. In the meantime, provide guidance based on the analysis tools that are available.

### URL not accessible
```
Error: Failed to fetch URL (timeout/403/etc)
```
**Response:** The URL may be blocked, require authentication, or have firewall rules. Suggest:
1. Check if the URL is accessible in a browser
2. Try without `renderJs` (some sites block headless browsers)
3. The site may block automated requests

### Rate limit exceeded
```
Error: PageSpeed API rate limit exceeded
```
**Response:** Wait 100 seconds and retry, or suggest the user add a `PAGESPEED_API_KEY` for higher limits.

---

## Tool Combinations That Work Well Together

| Combination | Use Case |
|-------------|----------|
| `analyze_page` → `generate_meta_suggestions` | Quick on-page fix recommendations |
| `analyze_page` → `analyze_headings` → `analyze_images` | Content page deep dive |
| `extract_schema` → `generate_schema` | Fix or add structured data |
| `analyze_robots_txt` → `analyze_sitemap` | Crawlability foundation check |
| `check_core_web_vitals` → `check_mobile_friendly` | Performance + mobile audit |
| `analyze_backlinks` → `analyze_domain_authority` | Off-page profile assessment |
| `research_keywords` → `analyze_serp` | Keyword opportunity analysis |
| `gsc_performance` → `analyze_page` (top pages) | Data-driven page optimization |
