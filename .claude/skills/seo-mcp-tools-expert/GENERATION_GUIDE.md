# Generation Tools Guide

Guide for schema, robots.txt, and meta tag generation tools.

---

## generate_schema

Generates valid JSON-LD markup for any supported Schema.org type.

### Supported types
Article, BlogPosting, NewsArticle, Product, FAQPage, HowTo, LocalBusiness (and subtypes), Organization, BreadcrumbList, WebSite, Event, Recipe, VideoObject, Course, SoftwareApplication, Review, Person, JobPosting

### Usage pattern
```
generate_schema({
  type: "Article",
  data: {
    headline: "How to Do an SEO Audit",
    description: "Step-by-step guide to SEO auditing",
    author: { name: "John Doe", url: "https://example.com/authors/john" },
    datePublished: "2026-01-15",
    dateModified: "2026-02-20",
    image: "https://example.com/images/seo-audit.jpg",
    publisher: { name: "Example Blog", logo: "https://example.com/logo.png" }
  },
  validate: true
})
```

### What it returns
```
{
  jsonLd: {
    "@context": "https://schema.org",
    "@type": "Article",
    "headline": "How to Do an SEO Audit",
    ...
  },
  htmlSnippet: '<script type="application/ld+json">\n{...}\n</script>',
  validation: {
    valid: true,
    errors: [],
    warnings: ["Missing recommended property: mainEntityOfPage"],
    googleEligible: true,
    richResultType: "Article"
  }
}
```

### Tips
- Always use `validate: true` to catch missing required properties
- The `htmlSnippet` is ready to paste into your page's `<head>`
- Check `validation.warnings` for recommended properties that improve rich result chances
- For LocalBusiness subtypes, use the specific type (e.g., "Restaurant", "Plumber", "LegalService")

### Common data requirements by type

| Type | Required Data |
|------|--------------|
| Article | headline, author, datePublished, image, publisher |
| Product | name, image, offers (price, currency, availability) |
| FAQPage | questions (array of {question, answer}) |
| HowTo | name, steps (array of {name, text}) |
| LocalBusiness | name, address, telephone |
| BreadcrumbList | items (array of {name, url}) |
| Event | name, startDate, location |
| Recipe | name, image, author, prepTime, cookTime, ingredients, instructions |

---

## generate_robots_txt

Generates a robots.txt file based on configuration.

### Usage pattern
```
generate_robots_txt({
  sitemapUrls: ["https://example.com/sitemap.xml"],
  disallowPaths: ["/admin/", "/api/", "/staging/"],
  allowPaths: ["/api/public/"],
  preset: "standard"
})
```

### Presets
| Preset | Description |
|--------|-------------|
| `permissive` | Allow all crawling, only block admin paths |
| `standard` | Block admin, API, staging, sort/filter params |
| `restrictive` | Block everything except explicitly allowed paths |

### What it returns
```
{
  content: "User-agent: *\nAllow: /\nDisallow: /admin/\n...\nSitemap: https://...",
  explanation: [
    "Allows all crawlers to access the site",
    "Blocks /admin/ - admin panel",
    "Blocks /api/ - API endpoints",
    "References sitemap for discovery"
  ],
  warnings: [],
  suggestions: ["Consider adding Disallow for search result pages if applicable"]
}
```

---

## generate_meta_suggestions

Analyzes a page and suggests improved meta tags.

### Usage pattern
```
generate_meta_suggestions({
  url: "https://example.com/seo-guide",
  targetKeyword: "SEO guide",
  secondaryKeywords: ["SEO tutorial", "learn SEO", "SEO for beginners"]
})
```

### What it returns
```
{
  current: {
    title: "Blog | Example.com",
    description: null,
    ogTitle: null,
    ogDescription: null,
    ogImage: null
  },

  issues: [
    "Title is generic and doesn't contain target keyword",
    "Meta description is missing",
    "Open Graph tags are missing"
  ],

  suggestions: {
    title: {
      text: "SEO Guide for Beginners: Learn SEO Step by Step | Example",
      length: 56,
      keywordPosition: 0,
      improvement: "Added target keyword at start, made specific and compelling"
    },
    metaDescription: {
      text: "Learn SEO with this comprehensive beginner's guide. Covers on-page optimization, technical SEO, and content strategy. Start improving your rankings today.",
      length: 155,
      improvement: "Created compelling description with keyword, CTA, and value proposition"
    },
    ogTitle: {
      text: "SEO Guide for Beginners: Learn SEO Step by Step",
      improvement: "Matches title without brand suffix for cleaner social sharing"
    },
    ogDescription: {
      text: "Comprehensive SEO tutorial covering everything from keyword research to technical auditing. Perfect for beginners.",
      improvement: "Concise social-friendly description"
    }
  }
}
```

### When to use
- After `analyze_page` shows meta tag issues
- When optimizing a page for a specific keyword
- When planning content and want to draft meta tags
- Always provide `targetKeyword` for best results
- `secondaryKeywords` helps generate more natural, varied suggestions
