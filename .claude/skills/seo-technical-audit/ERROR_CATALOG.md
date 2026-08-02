# Technical SEO Error Catalog

Complete catalog of technical SEO issues organized by category and severity.

---

## Severity Levels

| Level | Description | Action |
|-------|-------------|--------|
| Critical | Blocks indexing or causes major ranking loss | Fix immediately |
| High | Significant negative SEO impact | Fix within 1 week |
| Medium | Moderate impact on SEO performance | Fix within 1 month |
| Low | Minor impact, best practice improvement | Fix when convenient |

---

## Crawlability Issues

### ROBOTS_BLOCKING_IMPORTANT (Critical)
**Description:** robots.txt blocks crawling of important pages.
**Detection:** `analyze_robots_txt(domain, { testPath: "/important-page" })`
**Impact:** Blocked pages cannot be indexed at all.
**Fix:** Remove or modify the `Disallow` rule. Test with `testPath` parameter before deploying.

### ROBOTS_BLOCKING_CSS_JS (High)
**Description:** robots.txt blocks CSS or JavaScript files.
**Detection:** `analyze_robots_txt` → check for `/css/`, `/js/`, `.css`, `.js` in Disallow rules.
**Impact:** Google can't render the page properly, may see a broken version.
**Fix:** Remove CSS/JS blocking rules. Google needs these to render pages correctly.

### NOINDEX_ON_IMPORTANT_PAGE (Critical)
**Description:** Important page has `<meta name="robots" content="noindex">` or `X-Robots-Tag: noindex`.
**Detection:** `analyze_page` → check robots directives.
**Impact:** Page removed from search index entirely.
**Fix:** Remove the noindex directive. Verify with GSC URL Inspection.

### CRAWL_BUDGET_WASTE (Medium)
**Description:** Crawlers spend time on low-value pages (faceted nav, parameters, staging).
**Detection:** Review crawl stats in GSC; check robots.txt for missing parameter blocks.
**Impact:** Important pages get crawled less frequently.
**Fix:** Block low-value URL patterns in robots.txt, use noindex where appropriate.

---

## Indexing Issues

### MISSING_CANONICAL (High)
**Description:** Page lacks a canonical tag.
**Detection:** `analyze_page` → check canonical.
**Impact:** Duplicate versions may compete; Google chooses arbitrarily.
**Fix:** Add self-referencing canonical: `<link rel="canonical" href="https://...">`

### CANONICAL_MISMATCH (High)
**Description:** Canonical points to a different URL that returns 404, redirect, or noindex.
**Detection:** `analyze_page` → check canonical URL validity.
**Impact:** Google may ignore the canonical or deindex the page.
**Fix:** Ensure canonical points to a live, 200-status, indexable page.

### CANONICAL_CHAIN (Medium)
**Description:** Page A canonicals to Page B, which canonicals to Page C.
**Detection:** Follow canonical chain manually or via crawl.
**Impact:** Google may not follow the chain; unpredictable indexing.
**Fix:** All pages should canonical directly to the final preferred URL.

### DUPLICATE_CONTENT (High)
**Description:** Multiple URLs serve identical or near-identical content.
**Detection:** Compare page content across URL variants (www/non-www, HTTP/HTTPS, trailing slash).
**Impact:** Ranking signals split across duplicates.
**Fix:** Implement proper canonicals, 301 redirects, or consolidate pages.

### NOINDEX_IN_SITEMAP (Medium)
**Description:** Sitemap contains URLs that have noindex directives.
**Detection:** Cross-reference `analyze_sitemap` results with `analyze_page` robots checks.
**Impact:** Sends conflicting signals to search engines.
**Fix:** Remove noindex URLs from sitemap.

---

## Performance Issues

### SLOW_LCP (High)
**Description:** Largest Contentful Paint exceeds 2.5 seconds.
**Detection:** `check_core_web_vitals` → check LCP score.
**Impact:** Poor Core Web Vitals score; ranking disadvantage.
**Fix:** Optimize LCP element (preload image, reduce server response time, remove render-blocking resources).

### POOR_INP (High)
**Description:** Interaction to Next Paint exceeds 200ms.
**Detection:** `check_core_web_vitals` → check INP score.
**Impact:** Poor user experience and Core Web Vitals score.
**Fix:** Break up long JavaScript tasks, optimize event handlers, reduce DOM size.

### HIGH_CLS (High)
**Description:** Cumulative Layout Shift exceeds 0.1.
**Detection:** `check_core_web_vitals` → check CLS score.
**Impact:** Visual instability frustrates users; Core Web Vitals failure.
**Fix:** Set image dimensions, reserve ad space, preload fonts with `font-display: swap`.

### SLOW_TTFB (Medium)
**Description:** Time to First Byte exceeds 800ms.
**Detection:** `check_core_web_vitals` → check TTFB in server timing.
**Impact:** Delays all subsequent page load metrics.
**Fix:** Optimize server (caching, database queries, CDN, HTTP/2+).

### RENDER_BLOCKING_RESOURCES (Medium)
**Description:** CSS or JS files block page rendering.
**Detection:** `check_core_web_vitals` → check opportunities.
**Impact:** Delays first paint and LCP.
**Fix:** Inline critical CSS, defer non-critical CSS/JS, use `async`/`defer` attributes.

### LARGE_PAGE_SIZE (Medium)
**Description:** Total page weight exceeds 3MB.
**Detection:** `check_core_web_vitals` → check total resource size.
**Impact:** Slow load times, especially on mobile networks.
**Fix:** Compress images, minify CSS/JS, enable Brotli/gzip, remove unused code.

---

## Mobile Issues

### MISSING_VIEWPORT (Critical)
**Description:** Page lacks `<meta name="viewport">` tag.
**Detection:** `check_mobile_friendly` → check viewport.
**Impact:** Page renders at desktop width on mobile; unusable.
**Fix:** Add `<meta name="viewport" content="width=device-width, initial-scale=1">`.

### SMALL_TAP_TARGETS (Medium)
**Description:** Interactive elements smaller than 48x48px or too close together.
**Detection:** `check_mobile_friendly` → check tap targets.
**Impact:** Poor mobile usability; frustrating user experience.
**Fix:** Increase button/link sizes to minimum 48x48px with 8px spacing.

### SMALL_FONT_SIZE (Medium)
**Description:** Body text smaller than 16px on mobile.
**Detection:** `check_mobile_friendly` → check font sizes.
**Impact:** Text hard to read without zooming.
**Fix:** Set body font-size to at least 16px.

### CONTENT_WIDER_THAN_VIEWPORT (High)
**Description:** Content overflows horizontally on mobile.
**Detection:** `check_mobile_friendly` → check content width.
**Impact:** Horizontal scrolling required; poor experience.
**Fix:** Use responsive CSS (`max-width: 100%`, flexbox/grid).

---

## Security Issues

### MIXED_CONTENT (High)
**Description:** HTTPS page loads resources (images, scripts, styles) over HTTP.
**Detection:** `analyze_page` → check for HTTP resource URLs on HTTPS page.
**Impact:** Browser security warnings; potential content blocking.
**Fix:** Update all resource URLs to HTTPS.

### NO_HTTPS (Critical)
**Description:** Site not served over HTTPS.
**Impact:** "Not Secure" browser warning; ranking disadvantage; no HTTP/2.
**Fix:** Install SSL certificate, redirect HTTP → HTTPS.

### EXPIRED_CERTIFICATE (Critical)
**Description:** SSL certificate has expired.
**Impact:** Browser blocks access; immediate traffic loss.
**Fix:** Renew certificate immediately.

---

## Redirect Issues

### REDIRECT_CHAIN (High)
**Description:** More than 2 redirects in sequence (A → B → C → D).
**Detection:** `analyze_page` with `followRedirects: true` → check redirect chain.
**Impact:** Lost link equity at each hop; slower page load; crawl budget waste.
**Fix:** Update all redirects to point directly to the final destination.

### REDIRECT_LOOP (Critical)
**Description:** Redirects form a cycle (A → B → A).
**Impact:** Page is completely inaccessible.
**Fix:** Identify and break the loop by correcting redirect rules.

### TEMPORARY_REDIRECT_PERMANENT_MOVE (High)
**Description:** Using 302 (temporary) for a permanent URL change.
**Impact:** Link equity not transferred to new URL.
**Fix:** Change 302 to 301.

---

## Structured Data Issues

### MISSING_REQUIRED_SCHEMA_PROPERTY (High)
**Description:** Schema markup missing a property required by Google for rich results.
**Detection:** `extract_schema(url, { validateGoogle: true })` → check errors.
**Impact:** Page won't be eligible for rich results.
**Fix:** Add the missing required property. See seo-schema-structured-data skill.

### INVALID_SCHEMA_MARKUP (Medium)
**Description:** JSON-LD syntax error or invalid property values.
**Detection:** `extract_schema` → check validation errors.
**Impact:** Search engines ignore the structured data entirely.
**Fix:** Fix JSON syntax, correct property value types.

---

## International SEO Issues

### MISSING_HREFLANG (Medium)
**Description:** Multi-language site has no hreflang tags.
**Detection:** `analyze_page` → check for hreflang tags.
**Impact:** Wrong language version may show in search results for different countries.
**Fix:** Add bidirectional hreflang tags to all language versions.

### HREFLANG_NOT_BIDIRECTIONAL (High)
**Description:** Page A references Page B, but Page B doesn't reference Page A.
**Impact:** Google may ignore hreflang entirely.
**Fix:** Ensure every referenced page includes the complete set of hreflang tags.

### MISSING_X_DEFAULT (Medium)
**Description:** Hreflang set missing `x-default` tag.
**Impact:** No fallback for users in unsupported regions.
**Fix:** Add `<link rel="alternate" hreflang="x-default" href="...">` pointing to the default/language selector page.
