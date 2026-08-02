# HTTP Status Codes: SEO Reference

Complete reference for HTTP status codes and their SEO implications.

---

## 2xx Success

| Code | Name | SEO Impact | Action |
|------|------|------------|--------|
| 200 | OK | Expected for all indexable pages | None needed |
| 201 | Created | N/A (API responses) | N/A |
| 204 | No Content | Avoid for web pages | Return 200 with content |

---

## 3xx Redirection

| Code | Name | SEO Impact | Action |
|------|------|------------|--------|
| 301 | Moved Permanently | Passes ~95% link equity | Use for permanent URL changes |
| 302 | Found (Temporary) | Does NOT pass link equity long-term | Use only for genuinely temporary moves |
| 303 | See Other | N/A (post-redirect-get pattern) | N/A |
| 304 | Not Modified | Positive — efficient caching | None needed; working as intended |
| 307 | Temporary Redirect | Same as 302 but preserves HTTP method | Use for temporary moves with POST preservation |
| 308 | Permanent Redirect | Same as 301 but preserves HTTP method | Use for permanent moves with POST preservation |

### Redirect best practices
- **Always use 301** for permanent URL changes (site migrations, slug changes, domain moves)
- **Avoid redirect chains** — each hop loses a small amount of link equity
- **Update internal links** to point to the final URL (don't rely on redirects)
- **Maximum 2 hops** recommended (A → B is fine; A → B → C → D is not)
- **Monitor redirect chains** regularly — they tend to accumulate over time

---

## 4xx Client Errors

| Code | Name | SEO Impact | Action |
|------|------|------------|--------|
| 400 | Bad Request | N/A (shouldn't appear in crawl) | Fix server-side validation |
| 401 | Unauthorized | Blocks crawling of the page | Don't protect indexable content this way |
| 403 | Forbidden | Blocks crawling | Ensure important pages aren't 403'd |
| 404 | Not Found | Page removed from index over time | Remove from sitemap; fix internal links |
| 405 | Method Not Allowed | N/A (Googlebot uses GET) | N/A |
| 410 | Gone | Faster deindexing than 404 | Use when page is permanently removed |
| 429 | Too Many Requests | Slows crawling; can lose pages from index | Fix rate limiting to not block crawlers |
| 451 | Unavailable for Legal Reasons | Page removed from index | N/A |

### 404 vs 410
- **404:** "This page doesn't exist (maybe it never did, maybe it was removed)"
- **410:** "This page existed but has been permanently removed"
- Google treats 410 as a stronger signal for faster deindexing
- Use 410 when you intentionally remove content; 404 for pages that never existed

### Soft 404s
A "soft 404" is when a page returns 200 status but shows "page not found" content. Google can detect these.

**Problems:**
- Wastes crawl budget (Google crawls 200 pages expecting content)
- Confuses indexing (may index the "not found" page)

**Fix:**
- Return proper 404 status code for missing pages
- Customize your 404 page but ensure it returns the 404 status

---

## 5xx Server Errors

| Code | Name | SEO Impact | Action |
|------|------|------------|--------|
| 500 | Internal Server Error | Critical — blocks crawling and indexing | Fix the server error immediately |
| 502 | Bad Gateway | Same as 500 | Fix proxy/upstream server |
| 503 | Service Unavailable | Google retries; temporary | Use for planned maintenance with `Retry-After` header |
| 504 | Gateway Timeout | Same as 500 | Fix slow upstream servers |

### 503 for maintenance
When performing planned maintenance:
```http
HTTP/1.1 503 Service Unavailable
Retry-After: 3600
```
- Google will retry after the specified time
- Short outages (< 24 hours) generally don't affect rankings
- Extended 503s will cause pages to drop from the index

### Server error best practices
- Monitor for 5xx errors continuously
- Set up alerts for any 5xx response on important pages
- Fix 500 errors immediately — they block indexing
- Never return 5xx for legitimate pages (even temporarily)
- Check server logs for the root cause

---

## Status Code Decision Tree

```
Is the content available?
├── Yes → 200 OK
└── No
    ├── Moved permanently?
    │   ├── Yes → 301 (or 308 for POST preservation)
    │   └── Temporarily? → 302 (or 307 for POST preservation)
    ├── Removed permanently?
    │   └── Yes → 410 Gone
    ├── Never existed?
    │   └── Yes → 404 Not Found
    ├── Requires authentication?
    │   └── Yes → 401 or 403 (but don't protect indexable content)
    └── Server problem?
        ├── Temporary maintenance → 503 with Retry-After
        └── Bug → 500 (fix immediately)
```
