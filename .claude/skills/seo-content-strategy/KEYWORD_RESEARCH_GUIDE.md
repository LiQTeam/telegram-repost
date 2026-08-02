# Keyword Research Guide

A complete, step-by-step process for keyword research that feeds directly into content strategy and content brief creation.

---

## Step 1: Define Your Keyword Universe

Before opening any tool, establish the boundaries of your research.

### Inputs Required

| Input | Source | Example |
|-------|--------|---------|
| Core business topics | Product/service offerings | "email marketing", "marketing automation" |
| Target audience segments | Buyer personas | SMB owners, marketing managers, agencies |
| Business goals | Strategy documents | Increase trial signups, grow organic traffic |
| Geographic scope | Business model | US-only, global English, multi-language |
| Competitive set | Market knowledge | 3-5 direct organic competitors |

### Output

A list of 5-15 seed keywords that represent the broadest version of your target topics.

---

## Step 2: Generate Seed Keywords

Seed keywords are the starting point. They are typically 1-2 word phrases that define a category.

### Techniques

**Brainstorm from the business:**
```
Product categories:    "CRM software", "sales pipeline", "contact management"
Features:              "lead scoring", "email automation", "deal tracking"
Problems solved:       "sales forecasting", "customer churn", "pipeline visibility"
Audience terms:        "sales team tools", "startup CRM", "enterprise sales"
```

**Extract from existing data:**
- Google Search Console > Performance > Queries (sort by impressions)
- Google Analytics > Acquisition > Organic search queries
- Internal site search logs
- Customer support ticket keyword frequency

**Mine competitors:**
- Read competitor homepage copy, navigation, and H1 tags
- Check competitor meta titles across key pages
- Review competitor blog category names

**MCP Tool:** Use `analyze_page` on 3-5 competitor homepages to extract their primary keyword targets from title tags, H1s, and meta descriptions.

---

## Step 3: Expand to Long-Tail Keywords

Each seed keyword should generate 20-100 long-tail variations.

### Expansion Methods

| Method | Process | Yield |
|--------|---------|-------|
| Google Autocomplete | Type seed + each letter a-z | 20-50 per seed |
| People Also Ask | Search seed, expand all PAA boxes, search those, repeat | 10-30 per seed |
| Related Searches | Scroll to bottom of Google SERP | 8 per search |
| Forum mining | `site:reddit.com "[seed]"` or `site:quora.com "[seed]"` | 10-30 per seed |
| Competitor content | Scan competitor blog titles and H2 headings | 15-40 per seed |
| Answer the Public | Free tool, generates question/preposition variations | 50-100 per seed |
| Google Keyword Planner | Free with Google Ads account, "Discover new keywords" | 50-200 per seed |
| AlsoAsked.com | Maps PAA question trees visually | 20-40 per seed |

### Modifier Categories

Apply these modifiers systematically to each seed:

```
Adjective modifiers:   best, top, free, cheap, affordable, premium, simple
Audience modifiers:    for beginners, for small business, for enterprise, for teams
Comparison modifiers:  vs, alternative, comparison, like [competitor]
Year modifiers:        2025, 2026
Intent modifiers:      how to, what is, guide, tutorial, template, checklist
Format modifiers:      tool, software, app, platform, plugin, extension
Qualifier modifiers:   with [feature], without [limitation], in [location]
```

**MCP Tool:** Use `research_keywords` with `expand: true` and the seed keyword. The tool returns related keywords, search volumes, and difficulty scores. Run once per seed keyword.

---

## Step 4: Mine Question Keywords

Question keywords are critical for featured snippets, PAA boxes, and voice search optimization.

### Sources

1. **People Also Ask (PAA):** Search your seed keyword, click every PAA result to expand the list, record all questions. Each click generates 2-4 new questions.

2. **Forum and community sites:**
   ```
   site:reddit.com "keyword"
   site:quora.com "keyword"
   site:stackexchange.com "keyword"
   ```

3. **Autocomplete questions:** Type each question prefix before your seed:
   ```
   "how to [seed]"      "why does [seed]"      "can you [seed]"
   "what is [seed]"     "when to [seed]"       "does [seed]"
   "where to [seed]"    "which [seed]"         "is [seed]"
   ```

4. **Google's "Questions & Answers" SERP feature:** Some queries show a dedicated Q&A section.

5. **Customer data:** Support tickets, sales call transcripts, chatbot logs.

### Organizing Questions by Funnel Stage

| Funnel Stage | Question Pattern | Example |
|-------------|-----------------|---------|
| Awareness | "What is..." / "Why is..." | "What is a content cluster?" |
| Consideration | "How to..." / "Best way to..." | "How to build a content cluster?" |
| Decision | "Which is better..." / "[Product] vs..." | "HubSpot vs WordPress for content hubs?" |
| Post-purchase | "How to set up..." / "Troubleshoot..." | "How to measure content cluster performance?" |

---

## Step 5: Filter and Score Keywords

Not every keyword is worth targeting. Apply these filters:

### Filtering Criteria

| Filter | Threshold | Rationale |
|--------|-----------|-----------|
| Search volume | >10/mo (or >0 for YMYL/high-value) | Below this, traffic potential is negligible |
| Keyword difficulty | Within reach of your site's authority | New sites: KD < 30. Established sites: KD < 60. Authority sites: any KD |
| Relevance | Direct relation to business offering | High volume but irrelevant keywords waste resources |
| Intent match | You can create the right content type | If intent requires a tool and you only write articles, skip it |
| SERP opportunity | Not dominated by mega-brands or special features | If top 10 is all Wikipedia, government sites, or Amazon, reconsider |

### Disqualification Signals

Remove keywords that show:
- Top 10 results are all from domains with DA 80+ (and yours is DA 20)
- SERP is dominated by a single SERP feature you cannot replicate (e.g., Google's own calculator)
- The keyword is ambiguous and Google shows mixed intent (hard to rank for any single intent)
- The keyword has no commercial relevance to your business and does not support a cluster

---

## Step 6: Group Keywords by Intent and Topic

### Grouping Process

1. **Cluster by parent topic:** Group keywords that would be answered by the same page
2. **Assign primary keyword:** The highest-volume keyword in the group becomes the primary target
3. **Assign secondary keywords:** All other keywords in the group become secondary targets for the same page
4. **Classify intent:** Label each group as informational, commercial, transactional, or navigational

### Example Grouping

```
GROUP: "content calendar" (informational)
  Primary:     "content calendar" (6,600/mo, KD 45)
  Secondary:   "content calendar template" (4,400/mo, KD 35)
                "how to create a content calendar" (1,900/mo, KD 30)
                "editorial calendar" (1,600/mo, KD 40)
                "content planning template" (880/mo, KD 25)
                "social media content calendar" (2,400/mo, KD 38)
  Questions:   "what should a content calendar include?"
                "how far in advance should you plan content?"
```

One page targets this entire group. Do NOT create separate pages for "content calendar" and "content calendar template" — they share the same intent and would cannibalize each other.

---

## Step 7: Prioritize with the Impact Matrix

Score each keyword group on four dimensions, each rated 1-5:

| Dimension | Score 1 | Score 5 |
|-----------|---------|---------|
| **Volume** | <100/mo | >5,000/mo |
| **Difficulty** | KD 80+ (hard to rank) | KD 0-20 (easy to rank) |
| **Relevance** | Tangentially related | Core product/service keyword |
| **Business value** | No conversion path | Direct revenue/signup driver |

### Priority Formula

```
Priority Score = (Volume + Difficulty + Relevance + Business Value) / 4
```

| Priority Score | Action |
|---------------|--------|
| 4.0-5.0 | Create immediately — highest impact |
| 3.0-3.9 | Create within 30 days |
| 2.0-2.9 | Create within 90 days |
| 1.0-1.9 | Backlog — create only if resources allow |

### Alternative: Weighted Formula

If business value matters more than traffic:

```
Priority = (Volume * 0.15) + (Difficulty * 0.20) + (Relevance * 0.25) + (Business Value * 0.40)
```

---

## Step 8: Map Keywords to Content Types

| Intent | Content Type | Typical Word Count |
|--------|-------------|-------------------|
| Informational — broad | Pillar page / ultimate guide | 3,000-5,000 |
| Informational — specific | Blog post / tutorial | 1,500-2,500 |
| Informational — question | FAQ section or short post | 500-1,500 |
| Commercial investigation | Comparison / review / "best of" | 2,000-4,000 |
| Transactional | Product page / pricing page / landing page | 500-1,500 |
| Navigational | Homepage / brand page | 400-800 |

---

## MCP Tool Reference: `research_keywords`

### Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `keyword` | string | Yes | The seed keyword to research |
| `expand` | boolean | No | Return long-tail variations (default: false) |
| `country` | string | No | Two-letter country code for localized data (default: "us") |
| `language` | string | No | Language code (default: "en") |

### Interpreting Results

The tool returns an array of keyword objects:

```
keyword:           The keyword phrase
volume:            Monthly search volume (averaged over 12 months)
difficulty:        0-100 score (higher = harder to rank)
cpc:               Cost-per-click in Google Ads (indicator of commercial value)
trend:             12-month trend direction (up, down, stable)
serp_features:     Array of SERP features present for this keyword
```

### Tips for Best Results

- Run the tool once per seed keyword, not once per long-tail (to avoid rate limiting)
- Use `expand: true` to get related variations automatically
- Cross-reference volume data with Google Search Console impression data for keywords you already rank for
- CPC > $5 indicates strong commercial value — prioritize these even at lower volumes
- Check the `trend` field — an "up" trend keyword at 500/mo may be worth more than a "down" trend keyword at 2,000/mo

---

## Related Files

- [SKILL.md](SKILL.md) — Full content strategy guide including intent, clusters, E-E-A-T, and briefs
- [CONTENT_CLUSTER_TEMPLATES.md](CONTENT_CLUSTER_TEMPLATES.md) — Ready-to-use cluster templates for mapping keyword groups to content
- [SEARCH_INTENT_PATTERNS.md](SEARCH_INTENT_PATTERNS.md) — Detailed intent classification for assigning keywords to content types
