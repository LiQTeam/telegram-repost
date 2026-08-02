# Performance Tools Guide

Guide for Core Web Vitals and mobile-friendliness tools.

---

## check_core_web_vitals

Uses Google PageSpeed Insights API v5 (free, optional API key for higher rate limits).

### What it returns
```
{
  url: string,
  strategy: "mobile" | "desktop",

  coreWebVitals: {
    LCP: { value: 2.1, unit: "s", rating: "good" },
    INP: { value: 180, unit: "ms", rating: "good" },
    CLS: { value: 0.05, unit: "score", rating: "good" },
    FCP: { value: 1.2, unit: "s", rating: "good" },
    TTFB: { value: 450, unit: "ms", rating: "good" }
  },

  lighthouseScores: {
    performance: 85,
    seo: 92,
    accessibility: 78,
    bestPractices: 90
  },

  fieldData: {                    // Real user data (CrUX) — may be null
    available: true,
    LCP: { p75: 2.3, rating: "good" },
    INP: { p75: 150, rating: "good" },
    CLS: { p75: 0.08, rating: "good" }
  },

  opportunities: [
    {
      title: "Serve images in next-gen formats",
      savings: "1.2s",
      description: "WebP and AVIF provide better compression..."
    }
  ],

  diagnostics: [
    {
      title: "Reduce initial server response time",
      description: "TTFB was 1.2s...",
      value: "1,200 ms"
    }
  ],

  resources: {
    totalSize: 2450000,
    requestCount: 45,
    byType: {
      image: { size: 1200000, count: 12 },
      script: { size: 800000, count: 15 },
      stylesheet: { size: 200000, count: 5 },
      font: { size: 150000, count: 3 },
      other: { size: 100000, count: 10 }
    }
  }
}
```

### Interpreting scores

#### Core Web Vitals ratings
| Metric | Good | Needs Improvement | Poor |
|--------|------|-------------------|------|
| LCP | ≤ 2.5s | ≤ 4.0s | > 4.0s |
| INP | ≤ 200ms | ≤ 500ms | > 500ms |
| CLS | ≤ 0.1 | ≤ 0.25 | > 0.25 |

#### Lighthouse score ranges
| Score | Rating | Color |
|-------|--------|-------|
| 90-100 | Good | Green |
| 50-89 | Needs Improvement | Orange |
| 0-49 | Poor | Red |

### Field data vs Lab data
- **Field data (CrUX):** Real user measurements aggregated over 28 days. Only available for pages with enough traffic. This is what Google uses for ranking.
- **Lab data (Lighthouse):** Simulated test from a controlled environment. Available for all pages. Useful for debugging but may not match real user experience.

**Always prioritize field data** when available. If field data shows "good" but lab data shows "poor", the real-world experience is likely fine.

### Common optimization recommendations by metric

#### Poor LCP (> 2.5s)
1. Check TTFB — if slow, optimize server (CDN, caching, database)
2. Check if LCP element is an image — preload it: `<link rel="preload">`
3. Check for render-blocking CSS/JS — inline critical CSS, defer the rest
4. Check if lazy-loading the LCP element — remove `loading="lazy"` from it

#### Poor INP (> 200ms)
1. Check for long JavaScript tasks — break into smaller chunks
2. Check DOM size — target under 1,500 nodes
3. Check third-party scripts — defer or lazy-load
4. Check heavy event handlers — debounce/throttle

#### Poor CLS (> 0.1)
1. Check images without `width`/`height` — add dimensions
2. Check for injected content (ads, banners) — reserve space
3. Check web fonts — use `font-display: swap` + preload
4. Check dynamic content — reserve layout space

### Rate limits
- **Without API key:** 25 requests per 100 seconds
- **With API key:** 400 requests per 100 seconds
- For auditing multiple pages, consider adding `PAGESPEED_API_KEY`

---

## check_mobile_friendly

Uses PageSpeed Insights with mobile strategy, focused on mobile usability.

### What it returns
```
{
  url: string,
  mobileFriendly: true | false,

  checks: {
    viewport: {
      configured: true,
      content: "width=device-width, initial-scale=1"
    },
    fontSizes: {
      legible: true,
      smallTextPercentage: 5       // % of text too small
    },
    tapTargets: {
      adequate: true,
      tooSmallCount: 2,
      tooCloseCount: 1
    },
    contentWidth: {
      fitsViewport: true,
      horizontalScrolling: false
    }
  },

  mobileLighthouseScore: 82,

  issues: [
    {
      type: "small_tap_targets",
      severity: "medium",
      detail: "2 tap targets are smaller than 48x48px",
      elements: [".nav-link", ".footer-link"]
    }
  ]
}
```

### When to use
- After `check_core_web_vitals` if mobile scores are low
- When users report mobile usability issues
- During a technical audit
- Always test mobile — Google uses mobile-first indexing

### Key mobile requirements
| Check | Requirement |
|-------|-------------|
| Viewport | `<meta name="viewport" content="width=device-width, initial-scale=1">` |
| Font size | ≥ 16px body text |
| Tap targets | ≥ 48x48px with ≥ 8px spacing |
| Content width | No horizontal scrolling |
| Interstitials | No full-screen popups on mobile |
