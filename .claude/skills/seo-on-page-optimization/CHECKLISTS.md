# On-Page SEO Audit Checklist

Step-by-step checklist for auditing on-page SEO. Use with MCP tools for automated checking.

---

## Full Page Audit Workflow

```
1. analyze_page(url, { includeContent: true })  -> Overall on-page score
2. analyze_headings(url, { targetKeyword })      -> Heading structure
3. analyze_images(url, { checkFileSize: true })  -> Image optimization
4. analyze_internal_links(url)                   -> Link quality
5. extract_schema(url)                           -> Structured data
6. generate_meta_suggestions(url, { targetKeyword }) -> Improvement suggestions
```

---

## Title Tag Checklist

- [ ] Title tag exists
- [ ] Length: 50-60 characters
- [ ] Contains primary keyword (ideally near start)
- [ ] Unique across the site (no duplicates)
- [ ] Includes brand name (typically at end)
- [ ] Matches search intent
- [ ] Compelling/click-worthy
- [ ] No keyword stuffing
- [ ] Uses separator correctly (`|`, `-`, or `:`)

**Pass criteria:** All checked = Pass. Missing title or duplicate = Fail.

---

## Meta Description Checklist

- [ ] Meta description exists
- [ ] Length: 150-160 characters
- [ ] Contains primary keyword
- [ ] Unique across the site
- [ ] Includes a call-to-action
- [ ] Compelling and accurate
- [ ] No double quotes (truncation risk)
- [ ] Written for humans, not bots

**Pass criteria:** All checked = Pass. Missing description = Warning (not as critical as title).

---

## Heading Structure Checklist

- [ ] Exactly one H1 on the page
- [ ] H1 contains primary keyword
- [ ] H1 matches page topic and search intent
- [ ] No skipped heading levels (H1 > H2 > H3)
- [ ] H2s contain secondary keywords where natural
- [ ] No empty headings
- [ ] Headings not used purely for styling
- [ ] Logical content hierarchy

**Pass criteria:** Single H1 + no skipped levels = Pass. Multiple H1 or skipped levels = Fail.

---

## Image SEO Checklist

- [ ] All non-decorative images have descriptive alt text
- [ ] Alt text under 125 characters
- [ ] No keyword-stuffed alt text
- [ ] Decorative images use `alt=""`
- [ ] Images under 200KB each
- [ ] Modern formats used (WebP/AVIF preferred)
- [ ] Width and height attributes set (prevents CLS)
- [ ] Below-the-fold images use `loading="lazy"`
- [ ] Responsive images use `srcset` where appropriate
- [ ] File names are descriptive with hyphens

**Pass criteria:** All images have alt text + under 200KB + modern format = Pass.

---

## Internal Linking Checklist

- [ ] Page has contextual internal links in body content
- [ ] Anchor text is descriptive (not "click here")
- [ ] No broken internal links (404s)
- [ ] Links point to relevant, related pages
- [ ] Important pages receive internal links
- [ ] No excessive links (under 100-150 per page)
- [ ] Navigation links are functional
- [ ] No orphan pages (every important page linked from at least one other)

**Pass criteria:** Descriptive anchors + no broken links = Pass.

---

## URL Structure Checklist

- [ ] URL is clean and readable
- [ ] Uses hyphens (not underscores or spaces)
- [ ] Lowercase only
- [ ] Contains primary keyword
- [ ] Under 3-4 directory levels deep
- [ ] No unnecessary parameters
- [ ] No session IDs in URL
- [ ] Consistent trailing slash usage

---

## Canonical Tag Checklist

- [ ] Canonical tag present
- [ ] Self-referencing (points to current page URL)
- [ ] Uses absolute URL (not relative)
- [ ] Points to HTTPS version
- [ ] Consistent www/non-www
- [ ] Does not point to a 404 or redirect
- [ ] No conflicting canonicals (HTTP header vs HTML tag)

---

## Open Graph / Social Checklist

- [ ] `og:title` present and compelling
- [ ] `og:description` present
- [ ] `og:image` present and correct dimensions (1200x630px min)
- [ ] `og:url` present with canonical URL
- [ ] `og:type` present
- [ ] `twitter:card` present (`summary_large_image` preferred)
- [ ] `twitter:title` present
- [ ] `twitter:description` present
- [ ] `twitter:image` present
- [ ] Image file under 5MB

---

## Content Quality Checklist

- [ ] Content matches search intent
- [ ] Meets minimum word count for page type
- [ ] 100% original (no copied/scraped content)
- [ ] Primary keyword in first 100 words
- [ ] Secondary keywords used naturally throughout
- [ ] Proper formatting (paragraphs, lists, tables)
- [ ] Includes multimedia (images, videos) where appropriate
- [ ] Good readability (short sentences, clear language)
- [ ] No thin content (sufficient depth for the topic)
- [ ] Regularly updated if time-sensitive

---

## Scoring Guide

| Score | Rating | Action |
|-------|--------|--------|
| 90-100 | Excellent | Minor tweaks only |
| 75-89 | Good | Fix high-priority items |
| 50-74 | Needs Work | Address all High + Critical issues |
| Below 50 | Poor | Major overhaul needed |
