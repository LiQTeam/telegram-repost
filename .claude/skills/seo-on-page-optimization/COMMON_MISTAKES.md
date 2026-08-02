# On-Page SEO: Common Mistakes

15 frequent on-page SEO mistakes with detection and fixes.

---

## Quick Reference

| # | Mistake | Severity | Detection |
|---|---------|----------|-----------|
| 1 | Missing or duplicate title tag | Critical | `analyze_page` |
| 2 | Title tag too long/short | High | `analyze_page` |
| 3 | Missing meta description | High | `analyze_page` |
| 4 | Multiple H1 tags | High | `analyze_headings` |
| 5 | Skipped heading levels | Medium | `analyze_headings` |
| 6 | Missing image alt text | High | `analyze_images` |
| 7 | Keyword-stuffed alt text | Medium | `analyze_images` |
| 8 | Non-descriptive anchor text | Medium | `analyze_internal_links` |
| 9 | Missing canonical tag | High | `analyze_page` |
| 10 | Duplicate content across pages | Critical | `analyze_page` (check canonical) |
| 11 | Missing Open Graph tags | Medium | `analyze_page` |
| 12 | Unoptimized images (large files) | High | `analyze_images` |
| 13 | Thin content | High | `analyze_page` (includeContent) |
| 14 | Orphan pages (no internal links) | Medium | `analyze_internal_links` |
| 15 | Dynamic URLs with parameters | Medium | Manual review |

---

## 1. Missing or Duplicate Title Tag

**Problem:** Page has no `<title>` tag, or multiple pages share the same title.

**Impact:** Critical — title is the #1 on-page ranking factor. Google may generate its own title, which is often worse.

**Detection:**
```
MCP: analyze_page(url) -> check title.text and title.issues
```

**Fix:**
- Add a unique `<title>` to every page
- Include primary keyword near the start
- Keep between 50-60 characters

---

## 2. Title Tag Too Long or Too Short

**Problem:** Title exceeds 60 characters (gets truncated in SERP) or is under 30 characters (misses keyword opportunity).

**Impact:** High — truncated titles lose click-through potential; short titles miss ranking signals.

**Fix:**
- Aim for 50-60 characters
- If truncated, move the most important keyword/info to the front
- Use `|` or `-` as separators to structure title efficiently

---

## 3. Missing Meta Description

**Problem:** Page has no `<meta name="description">` tag.

**Impact:** High — Google generates a snippet from page content, which may not be compelling.

**Fix:**
- Add a unique meta description to every page
- 150-160 characters
- Include primary keyword and a call-to-action
- Write for humans (persuasive, click-worthy)

---

## 4. Multiple H1 Tags

**Problem:** Page has more than one `<h1>` element.

**Impact:** High — dilutes the primary topic signal. Search engines may be confused about the main topic.

**Detection:**
```
MCP: analyze_headings(url) -> check issues for "multiple H1"
```

**Fix:**
- Keep exactly one H1 per page
- H1 should contain the primary keyword
- Convert extra H1s to H2s

---

## 5. Skipped Heading Levels

**Problem:** Heading hierarchy jumps levels (e.g., H1 directly to H3, skipping H2).

**Impact:** Medium — hurts accessibility and semantic structure. Search engines use heading hierarchy to understand content.

**Detection:**
```
MCP: analyze_headings(url) -> check issues for "skipped levels"
```

**Fix:**
- Follow strict hierarchy: H1 > H2 > H3 > H4
- Never skip levels
- Use CSS for visual styling, not heading tags

---

## 6. Missing Image Alt Text

**Problem:** Images have no `alt` attribute or empty `alt=""` on non-decorative images.

**Impact:** High — missed ranking opportunity in image search, hurts accessibility, and wastes a keyword signal.

**Detection:**
```
MCP: analyze_images(url) -> check missingAlt count
```

**Fix:**
- Add descriptive alt text to every non-decorative image
- Keep under 125 characters
- Include keyword naturally where relevant
- Use `alt=""` ONLY for purely decorative images

---

## 7. Keyword-Stuffed Alt Text

**Problem:** Alt text crammed with keywords: `alt="shoes running shoes best running shoes buy shoes online"`

**Impact:** Medium — Google penalizes keyword stuffing; hurts accessibility.

**Fix:**
- Describe what the image actually shows
- One natural keyword mention is sufficient
- `alt="Blue Nike Air Max running shoes on a forest trail"`

---

## 8. Non-Descriptive Anchor Text

**Problem:** Internal links use generic text like "click here", "read more", "this page".

**Impact:** Medium — anchor text is a ranking signal. Descriptive anchors help Google understand the linked page's topic.

**Detection:**
```
MCP: analyze_internal_links(url) -> check anchor text quality
```

**Fix:**
- Use descriptive, keyword-relevant anchor text
- `"our technical SEO audit guide"` instead of `"click here"`
- Vary anchor text naturally (don't use the exact same anchor every time)

---

## 9. Missing Canonical Tag

**Problem:** Page has no `<link rel="canonical">` tag.

**Impact:** High — without a canonical, duplicate versions (www vs non-www, HTTP vs HTTPS, parameters) may compete with each other.

**Fix:**
- Add self-referencing canonical to every indexable page
- Use absolute URLs: `<link rel="canonical" href="https://example.com/page">`
- Ensure it points to the preferred version (HTTPS, consistent www)

---

## 10. Duplicate Content Across Pages

**Problem:** Multiple pages have identical or near-identical content.

**Impact:** Critical — search engines may index the wrong version, or split ranking signals across duplicates.

**Fix:**
- Consolidate truly duplicate pages (301 redirect or canonical)
- For similar products/locations, add unique content to each page
- Use canonical tags to point to the preferred version
- Check for common causes: URL parameters, print versions, HTTP/HTTPS duplicates

---

## 11. Missing Open Graph Tags

**Problem:** No OG tags, causing poor social sharing appearance.

**Impact:** Medium — doesn't affect search rankings directly, but dramatically impacts social CTR and link sharing.

**Fix:**
- Add at minimum: `og:title`, `og:description`, `og:image`, `og:url`, `og:type`
- Image should be 1200x630px minimum
- Test with Facebook Sharing Debugger

---

## 12. Unoptimized Images (Large Files)

**Problem:** Images over 200KB-500KB slowing page load.

**Impact:** High — directly impacts Core Web Vitals (LCP) and user experience.

**Detection:**
```
MCP: analyze_images(url, { checkFileSize: true }) -> check oversized images
```

**Fix:**
- Compress images (80-85% quality JPEG is usually indistinguishable)
- Use modern formats (WebP, AVIF)
- Resize to maximum display dimensions (don't serve 4000px images for 800px displays)
- Implement lazy loading for below-the-fold images
- Use responsive images with `srcset`

---

## 13. Thin Content

**Problem:** Page has very little text content (under 200-300 words for a page that should be content-rich).

**Impact:** High — thin content pages struggle to rank and may trigger Google's thin content quality issues.

**Detection:**
```
MCP: analyze_page(url, { includeContent: true }) -> check wordCount
```

**Fix:**
- Add substantive, original content that matches search intent
- Aim for minimum word counts by page type (see SKILL.md)
- Don't add filler — quality over quantity
- Consider whether the page should exist at all (merge with another page?)

---

## 14. Orphan Pages (No Internal Links)

**Problem:** Important pages have zero internal links pointing to them.

**Impact:** Medium — search engines may not discover these pages, and they receive no internal link equity.

**Fix:**
- Add contextual internal links from related content
- Include in site navigation if appropriate
- Add to XML sitemap (as a safety net, not a fix)
- Run a site crawl to identify all orphan pages

---

## 15. Dynamic URLs with Parameters

**Problem:** URLs like `/products?id=123&color=blue&sort=price` instead of `/products/blue-running-shoes`.

**Impact:** Medium — parameter URLs are harder to read, share, and can create duplicate content issues.

**Fix:**
- Implement clean URL slugs where possible
- If parameters are necessary, use canonical tags
- Configure Google Search Console URL parameters handling
- Use `robots.txt` to block crawling of sort/filter parameter combinations
