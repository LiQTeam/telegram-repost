# Analysis Tools Guide

Detailed guide for the 7 page analysis MCP tools.

---

## analyze_page

The primary analysis tool. Start every SEO investigation here.

### What it returns
```
{
  url: string,                    // Final URL after redirects
  statusCode: number,             // HTTP status
  redirectChain: string[],        // Redirect hops (if any)
  responseTime: number,           // Server response time (ms)

  title: {
    text: string,                 // Title tag content
    length: number,               // Character count
    issues: string[]              // ["too_long", "missing", "duplicate"]
  },

  metaDescription: {
    text: string,
    length: number,
    issues: string[]
  },

  canonical: {
    url: string,
    isSelfReferencing: boolean,
    issues: string[]
  },

  robots: {
    meta: string,                 // Meta robots content
    xRobotsTag: string,           // X-Robots-Tag header
    isIndexable: boolean
  },

  openGraph: {
    title: string,
    description: string,
    image: string,
    url: string,
    type: string,
    issues: string[]
  },

  headings: {
    h1Count: number,
    h1Text: string[],
    totalHeadings: number,
    issues: string[]              // Quick heading check
  },

  images: {
    total: number,
    missingAlt: number,
    issues: string[]              // Quick image check
  },

  links: {
    internal: number,
    external: number,
    nofollow: number
  },

  content: {                      // Only with includeContent: true
    wordCount: number,
    readabilityScore: number
  },

  score: {
    overall: number,              // 0-100
    breakdown: {
      title: number,
      meta: number,
      headings: number,
      images: number,
      links: number,
      technical: number
    }
  }
}
```

### When to use
- **Always first** for any URL analysis
- Quick overview before drilling down with specific tools
- Comparing pages (run on multiple URLs)

### Tips
- Use `includeContent: true` when content quality matters
- Use `followRedirects: true` (default) to catch redirect chains
- Use `renderJs: true` only for SPAs (React/Vue/Angular sites)

---

## analyze_headings

Deep dive into heading structure.

### What it returns
```
{
  headingTree: [                  // Nested structure
    { tag: "h1", text: "...", children: [
      { tag: "h2", text: "...", children: [...] }
    ]}
  ],
  flatList: [
    { tag: "h1", text: "...", order: 1 },
    { tag: "h2", text: "...", order: 2 }
  ],
  counts: { h1: 1, h2: 5, h3: 8, h4: 2, h5: 0, h6: 0 },
  keywordPresence: {              // Only with targetKeyword
    inH1: true,
    inH2: ["Section heading with keyword"],
    count: 3
  },
  issues: [
    { type: "multiple_h1", severity: "high", detail: "Found 2 H1 tags" },
    { type: "skipped_level", severity: "medium", detail: "H1 -> H3 (skipped H2)" }
  ]
}
```

### When to use
- After `analyze_page` shows heading issues
- When optimizing content structure for a keyword
- Always pass `targetKeyword` if you know the target keyword

---

## analyze_images

Image SEO audit.

### What it returns
```
{
  images: [
    {
      src: "https://...",
      alt: "description" | null,
      width: 800,
      height: 600,
      loading: "lazy" | "eager" | null,
      format: "webp" | "jpg" | "png" | "gif" | "svg",
      fileSize: 145000,           // bytes, only with checkFileSize
      filenameQuality: "good"     // descriptive name or generic
    }
  ],
  summary: {
    total: 15,
    missingAlt: 3,
    emptyAlt: 1,
    oversized: 2,                 // > 200KB
    nonModernFormat: 5,           // not webp/avif
    missingDimensions: 4,
    missingLazyLoad: 8,           // below-fold without loading="lazy"
    score: 62                     // 0-100
  }
}
```

### When to use
- Image-heavy pages (galleries, product pages, portfolios)
- When CLS issues are suspected (missing dimensions)
- When page load is slow (oversized images)
- Set `checkFileSize: false` for faster runs (skips HEAD requests)

---

## analyze_internal_links

Link mapping and anchor text quality.

### What it returns
```
{
  internal: [
    { url: "...", anchor: "...", nofollow: false, position: "content" }
  ],
  external: [
    { url: "...", anchor: "...", nofollow: true, rel: "noopener" }
  ],
  broken: [                       // Only with checkBrokenLinks
    { url: "...", statusCode: 404, anchor: "..." }
  ],
  anchorTextAnalysis: {
    descriptive: 45,              // Good anchors
    generic: 12,                  // "click here", "read more"
    url: 3,                       // Naked URLs
    empty: 2                      // No text
  },
  summary: {
    internalCount: 62,
    externalCount: 15,
    nofollowCount: 8,
    brokenCount: 3,
    uniqueInternalDomains: 1,
    uniqueExternalDomains: 12
  }
}
```

### When to use
- Internal linking strategy review
- Broken link detection (set `checkBrokenLinks: true`)
- Anchor text quality audit
- Note: `checkBrokenLinks: true` is significantly slower (HEAD request per link)

---

## extract_schema

Structured data extraction and validation.

### What it returns
```
{
  schemas: [
    {
      format: "json-ld" | "microdata" | "rdfa",
      type: "Article",
      raw: { ... },               // Original parsed data
      validation: {
        valid: true,
        errors: [],
        warnings: ["Missing recommended property: dateModified"],
        googleEligible: true,
        richResultType: "Article"
      }
    }
  ],
  summary: {
    totalSchemas: 2,
    types: ["Article", "BreadcrumbList"],
    googleEligibleCount: 2,
    errorCount: 0,
    warningCount: 1
  }
}
```

### When to use
- Checking if a page has structured data
- Validating existing schema for Google rich result eligibility
- Before and after schema implementation
- Always use `validateGoogle: true` (default) for actionable results

---

## analyze_robots_txt

robots.txt parsing and rule testing.

### What it returns
```
{
  exists: true,
  content: "User-agent: *\nDisallow: /admin/\n...",
  rules: [
    { userAgent: "*", allow: ["/"], disallow: ["/admin/", "/api/"] }
  ],
  sitemaps: ["https://example.com/sitemap.xml"],
  testResult: {                   // Only with testPath
    path: "/admin/",
    userAgent: "Googlebot",
    allowed: false,
    matchingRule: "Disallow: /admin/"
  },
  issues: [
    { type: "blocking_css_js", severity: "high", detail: "..." }
  ]
}
```

---

## analyze_sitemap

XML sitemap validation.

### What it returns
```
{
  type: "urlset" | "sitemapindex",
  urlCount: 1234,
  urls: [...],                    // Truncated to maxUrls
  lastmodDistribution: {
    thisWeek: 15,
    thisMonth: 45,
    thisYear: 200,
    older: 989,
    missing: 0
  },
  issues: [
    { type: "stale_lastmod", severity: "medium", detail: "80% of URLs have lastmod older than 1 year" }
  ],
  urlCheck: [                     // Only with checkUrls
    { url: "...", statusCode: 404 }
  ]
}
```
