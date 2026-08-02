# Technical SEO Audit Workflow

Step-by-step methodology for conducting a complete technical SEO audit using seo-mcp tools.

---

## Overview

A technical SEO audit checks everything that affects how search engines crawl, index, render, and rank your site. This workflow uses MCP tools in the optimal order for efficiency.

**Total time estimate:** 15-30 minutes for a single site (depending on size and API key availability).

---

## Step 1: Crawlability Check

**Goal:** Ensure search engines can access your pages.

### Tools
```
analyze_robots_txt(domain)
analyze_robots_txt(domain, { testPath: "/important-page", userAgent: "Googlebot" })
```

### What to check
- [ ] Are important pages blocked by robots.txt?
- [ ] Is CSS/JS being blocked?
- [ ] Is the sitemap referenced in robots.txt?
- [ ] Are there overly broad Disallow rules?
- [ ] Is there a Crawl-delay set (unnecessary for Google)?

### Red flags
- `Disallow: /` blocking everything
- Blocking `/wp-content/` or `/assets/` (CSS/JS)
- Missing `Sitemap:` directive
- Blocking entire sections that should be indexed

---

## Step 2: Sitemap Validation

**Goal:** Verify the XML sitemap is valid and contains the right URLs.

### Tools
```
analyze_sitemap(domain)
analyze_sitemap(sitemapUrl, { checkUrls: true })  # slower but thorough
```

### What to check
- [ ] Sitemap exists and is accessible
- [ ] Valid XML structure
- [ ] URL count is reasonable (compare to expected indexable pages)
- [ ] `<lastmod>` dates are present and accurate
- [ ] No noindex pages in sitemap
- [ ] No 404/redirect URLs in sitemap
- [ ] Sitemap referenced in robots.txt

### Red flags
- Sitemap returns 404
- Contains URLs with noindex directives
- Contains URLs returning non-200 status codes
- Very outdated `<lastmod>` dates
- Over 50,000 URLs without using sitemap index

---

## Step 3: Page-Level Analysis

**Goal:** Check on-page technical elements for key pages.

### Tools
```
analyze_page(url, { includeContent: true, followRedirects: true })
analyze_headings(url, { targetKeyword: "primary keyword" })
analyze_images(url, { checkFileSize: true })
analyze_internal_links(url, { checkBrokenLinks: true })
```

### Priority pages to check
1. Homepage
2. Top landing pages (by traffic)
3. Category/hub pages
4. Sample product/content pages
5. Recently published pages

### What to check per page
- [ ] Title tag present, unique, correct length
- [ ] Meta description present, unique, correct length
- [ ] Single H1 with primary keyword
- [ ] Heading hierarchy (no skipped levels)
- [ ] Canonical tag present and self-referencing
- [ ] Meta robots not blocking indexing
- [ ] No redirect chains
- [ ] HTTP status is 200
- [ ] Images have alt text and are optimized
- [ ] Internal links use descriptive anchors
- [ ] No broken internal links

---

## Step 4: Core Web Vitals & Performance

**Goal:** Evaluate page speed and Core Web Vitals scores.

### Tools
```
check_core_web_vitals(url, { strategy: "mobile" })
check_core_web_vitals(url, { strategy: "desktop" })
```

### What to check
- [ ] LCP ≤ 2.5s (mobile)
- [ ] INP ≤ 200ms
- [ ] CLS ≤ 0.1
- [ ] Performance score ≥ 75
- [ ] SEO audit score ≥ 90
- [ ] No render-blocking resources
- [ ] Total page size under 3MB
- [ ] TTFB under 800ms

### Priority fixes (by impact)
1. Largest Contentful Paint (LCP) — biggest ranking impact
2. Cumulative Layout Shift (CLS) — user experience
3. Interaction to Next Paint (INP) — interactivity
4. Total page weight — crawl efficiency

---

## Step 5: Mobile Usability

**Goal:** Confirm the site is mobile-friendly.

### Tools
```
check_mobile_friendly(url)
```

### What to check
- [ ] Viewport meta tag present
- [ ] No horizontal scrolling
- [ ] Tap targets ≥ 48x48px
- [ ] Font size ≥ 16px body text
- [ ] No intrusive interstitials
- [ ] Content parity with desktop version

---

## Step 6: Structured Data Validation

**Goal:** Verify schema markup is present and valid.

### Tools
```
extract_schema(url, { validateGoogle: true })
```

### What to check
- [ ] Appropriate schema type for the page
- [ ] All required properties present (for Google rich results)
- [ ] Recommended properties included where possible
- [ ] No JSON-LD syntax errors
- [ ] Data matches visible page content
- [ ] Rich result eligibility confirmed

---

## Step 7: Search Console Data (if available)

**Goal:** Check real indexing and performance data from Google.

### Tools (require GSC OAuth2 setup)
```
gsc_index_coverage(siteUrl)
gsc_performance(siteUrl, { dimensions: ["page"], rowLimit: 50 })
gsc_sitemaps(siteUrl)
```

### What to check
- [ ] Index coverage: errors, warnings, excluded pages
- [ ] Sitemap submission status
- [ ] Top performing pages (clicks, impressions)
- [ ] Pages with high impressions but low CTR (meta tag optimization opportunity)
- [ ] Pages with declining position (content refresh opportunity)

---

## Audit Report Template

After completing all steps, compile findings into a prioritized report:

### Critical Issues (fix immediately)
- List all Critical severity findings
- Include: issue, affected URL(s), specific fix

### High Priority Issues (fix within 1 week)
- List all High severity findings
- Group by category (crawlability, indexing, performance, etc.)

### Medium Priority Issues (fix within 1 month)
- List all Medium severity findings

### Low Priority Improvements
- List all Low severity findings and best practice suggestions

### Scores Summary
| Category | Score | Status |
|----------|-------|--------|
| Crawlability | X/100 | Pass/Fail |
| Indexing | X/100 | Pass/Fail |
| Performance (Mobile) | X/100 | Pass/Fail |
| Performance (Desktop) | X/100 | Pass/Fail |
| Mobile Usability | X/100 | Pass/Fail |
| Structured Data | X/100 | Pass/Fail |
| Overall | X/100 | Pass/Fail |
