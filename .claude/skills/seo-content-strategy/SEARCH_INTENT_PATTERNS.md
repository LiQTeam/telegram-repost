# Search Intent Patterns

A comprehensive reference for classifying search intent, matching content formats to intent, and detecting intent mismatches that prevent pages from ranking.

---

## The Four Intent Types

### 1. Informational Intent

**Definition:** The searcher wants to learn something. They seek knowledge, explanations, instructions, or data. There is no immediate intent to buy or navigate to a specific site.

**User mindset:** "I want to know / understand / learn how."

**Share of all searches:** ~55-60%

---

### 2. Navigational Intent

**Definition:** The searcher wants to find a specific website, page, or brand. They already know where they want to go and are using Google as a shortcut.

**User mindset:** "I want to go to a specific place."

**Share of all searches:** ~10-15%

---

### 3. Commercial Investigation Intent

**Definition:** The searcher is researching before making a purchase decision. They are comparing options, reading reviews, and evaluating alternatives. They intend to buy, but not yet.

**User mindset:** "I want to evaluate my options before deciding."

**Share of all searches:** ~15-20%

---

### 4. Transactional Intent

**Definition:** The searcher wants to complete a specific action: buy a product, sign up for a service, download a file, or make a reservation.

**User mindset:** "I want to do / buy / get something right now."

**Share of all searches:** ~10-15%

---

## Signal Words by Intent Type

### Informational Signal Words

| Category | Signal Words / Patterns |
|----------|------------------------|
| Question prefixes | how to, what is, what are, why is, why do, when to, where is, who is |
| Learning | guide, tutorial, learn, explained, introduction, basics, meaning, definition |
| Process | steps, process, ways to, methods, techniques, tips, strategies |
| Reference | examples, list of, types of, history of, statistics, data, facts |
| Comparison (educational) | difference between, [A] vs [B] (conceptual) |

**Example queries (informational):**
```
"what is content marketing"
"how to do keyword research"
"difference between SEO and SEM"
"content marketing statistics 2026"
"types of search intent"
"why is page speed important for SEO"
"email marketing best practices"
"steps to create a marketing plan"
"history of Google algorithm updates"
"python list comprehension tutorial"
```

### Navigational Signal Words

| Category | Signal Words / Patterns |
|----------|------------------------|
| Brand names | [brand name], [product name], [company name] |
| Specific pages | [brand] login, [brand] pricing, [brand] support, [brand] contact |
| Official resources | [brand] documentation, [brand] API, [brand] blog |
| Direct access | official site, homepage, dashboard, portal, app |

**Example queries (navigational):**
```
"hubspot login"
"google search console"
"ahrefs pricing"
"shopify support"
"claude anthropic"
"twitter trending"
"amazon prime video"
"slack download"
"notion templates official"
"gmail inbox"
```

### Commercial Investigation Signal Words

| Category | Signal Words / Patterns |
|----------|------------------------|
| Evaluation | best, top, review, reviews, rating, comparison |
| Alternatives | [product] alternative, [product] alternatives, similar to [product], like [product] |
| Versus | [product A] vs [product B], [product A] or [product B], [product A] compared to [product B] |
| Qualification | pros and cons, advantages, disadvantages, is [product] worth it, is [product] good |
| Category shopping | best [category] for [use case], top [category] [year], [category] for beginners |

**Example queries (commercial investigation):**
```
"best project management software 2026"
"mailchimp vs convertkit"
"ahrefs review"
"is semrush worth the price"
"top CRM for small business"
"hubspot alternatives"
"shopify pros and cons"
"best laptop for video editing"
"standing desk comparison"
"noise cancelling headphones under $200"
```

### Transactional Signal Words

| Category | Signal Words / Patterns |
|----------|------------------------|
| Purchase | buy, purchase, order, shop, deal, discount, coupon, promo code, sale |
| Pricing | price, pricing, cost, cheap, affordable, how much, quote |
| Action | download, install, sign up, subscribe, register, book, reserve, hire, get |
| Urgency | near me, open now, same day, next day delivery, free shipping |
| Specific products | [exact product name + model number], [brand] [specific SKU] |

**Example queries (transactional):**
```
"buy macbook pro 16 inch"
"mailchimp pricing plans"
"download vscode"
"book dentist appointment near me"
"hire freelance writer"
"shopify free trial"
"nike air max 90 sale"
"register domain name"
"order business cards online"
"cheapest web hosting"
```

---

## SERP Feature Expectations by Intent

| SERP Feature | Informational | Navigational | Commercial | Transactional |
|-------------|:---:|:---:|:---:|:---:|
| Featured snippet (paragraph) | Frequent | Rare | Rare | Rare |
| Featured snippet (list) | Frequent | Rare | Sometimes | Rare |
| Featured snippet (table) | Sometimes | Rare | Sometimes | Rare |
| People Also Ask | Very frequent | Sometimes | Frequent | Sometimes |
| Knowledge panel | Sometimes | Frequent | Rare | Rare |
| Sitelinks | Rare | Very frequent | Rare | Rare |
| Image pack | Sometimes | Rare | Sometimes | Sometimes |
| Video carousel | Frequent (how-to) | Rare | Sometimes | Rare |
| Shopping results | Rare | Rare | Sometimes | Very frequent |
| Product listings / rich results | Rare | Rare | Frequent | Very frequent |
| Local pack / map | Rare | Sometimes | Sometimes | Frequent |
| Top stories / news | Sometimes | Rare | Rare | Rare |
| Reviews / star ratings | Rare | Rare | Very frequent | Frequent |
| Ads (search ads) | Rare | Sometimes | Frequent | Very frequent |

**How to use this table:** Search your target keyword and compare the SERP features you see against this table. The features present confirm the dominant intent Google assigns to that query.

**MCP Tool:** Use `analyze_serp` with the target keyword to get a structured breakdown of which SERP features appear and what content types dominate the results.

---

## Content Format Recommendations by Intent

### Informational Content Formats

| Query Pattern | Recommended Format | Key Elements |
|--------------|-------------------|-------------|
| "What is [X]" | Definition article | Clear definition in first paragraph (snippet-optimized), expanded explanation, examples |
| "How to [X]" | Step-by-step guide | Numbered steps, images per step, time estimate, materials list |
| "[X] vs [Y]" (conceptual) | Comparison article | Side-by-side table, clear distinctions, use-case recommendations |
| "[X] tips/strategies" | Listicle | Numbered tips, actionable advice, examples for each tip |
| "[X] examples" | Showcase / gallery | Visual examples, explanations, categorized examples |
| "[X] statistics" | Data roundup | Data tables, charts, source citations, key takeaways |

### Commercial Investigation Content Formats

| Query Pattern | Recommended Format | Key Elements |
|--------------|-------------------|-------------|
| "Best [X]" | Ranked listicle | Winner badge, mini-reviews, comparison table at top, criteria explained |
| "[A] vs [B]" (products) | Head-to-head comparison | Feature comparison table, pricing, pros/cons, verdict with reasoning |
| "[X] review" | In-depth review | Hands-on testing, screenshots, scoring system, pros/cons, final rating |
| "[X] alternatives" | Alternative roundup | Why users switch, feature comparison, price comparison, recommendation per use case |

### Transactional Content Formats

| Query Pattern | Recommended Format | Key Elements |
|--------------|-------------------|-------------|
| "Buy [X]" | Product page | Clear CTA, pricing, product images, reviews, shipping info, trust signals |
| "[X] pricing" | Pricing page | Plan comparison table, feature breakdowns, FAQ, CTA per plan |
| "Download [X]" | Download/landing page | Download button above fold, system requirements, version info |
| "[X] near me" | Local landing page | Address, map, hours, phone, reviews, service description |

---

## Intent Mismatch Detection

Intent mismatch is the most common reason well-written content fails to rank. If your content format does not match what Google rewards for a query, no amount of optimization will help.

### How to Detect Mismatches

1. **Search the target keyword** and examine the top 10 results
2. **Classify the dominant intent** of what ranks (not what you assume)
3. **Compare your content format** against what ranks

### Common Mismatch Patterns

| Your Content | SERP Shows | Problem | Fix |
|-------------|-----------|---------|-----|
| Blog post / guide | Product pages, shopping results | You wrote informational content for a transactional query | Create a product/pricing page instead |
| Product page | Blog posts, how-to guides | You created a sales page for an informational query | Create an educational guide, link to product page |
| Long-form guide | Short, direct answers in snippets | Google wants concise answers, not 3,000-word essays | Add a TL;DR or direct answer near the top, keep depth below |
| Comparison article | Single-brand review pages | Query intent is reviewing one product, not comparing many | Refocus on a single product review |
| Generic overview | Location-specific results with maps | Query has local intent you are not addressing | Create location-specific content or optimize for local SEO |
| Text-only article | Video carousel dominates SERP | Google prioritizes video for this query | Create a video or add video to the page |
| Outdated "[Year]" article | Fresh results from current year | Your content signals staleness | Update content, title, and data with current year |

### Intent Verification Checklist

Before creating content for any keyword, verify intent:

```
[ ] Searched the keyword in an incognito/private browser
[ ] Noted the content types in positions 1-5 (blog, product, tool, video, etc.)
[ ] Noted SERP features present (snippets, PAA, shopping, local pack)
[ ] Confirmed my planned content type matches the dominant format
[ ] Confirmed my planned content depth matches (short answer vs. comprehensive guide)
[ ] Checked whether intent is mixed (multiple formats ranking = opportunity to test)
[ ] If results are all mega-authority sites (Wikipedia, government) — reconsidered targeting
```

---

## Examples of Intent-Optimized Content Structure

### Example 1: Informational — "How to" Query

**Query:** "how to create a content calendar"

```
H1: How to Create a Content Calendar (Step-by-Step Guide)
  [Summary paragraph — direct answer to the question in 2-3 sentences]
  [Estimated time / what you'll need]
  H2: What Is a Content Calendar?
    [Brief definition — featured snippet target]
  H2: Step 1: Define Your Content Goals
    [Explanation + example]
  H2: Step 2: Audit Your Existing Content
    [Explanation + example]
  H2: Step 3: Choose Your Channels
    [Explanation + example]
  H2: Step 4: Build Your Calendar Template
    [Explanation + screenshot + downloadable template]
  H2: Step 5: Plan Your Content Themes
    [Explanation + example]
  H2: Step 6: Set Publishing Cadence
    [Explanation + example table]
  H2: Step 7: Assign Responsibilities
    [Explanation + RACI chart example]
  H2: Content Calendar Templates
    [3 free templates with download links]
  H2: Frequently Asked Questions
    [FAQ schema markup]
```

### Example 2: Commercial — "Best of" Query

**Query:** "best email marketing software for small business"

```
H1: Best Email Marketing Software for Small Business ([Year])
  [Quick verdict: top 3 picks in a summary table]
  [Selection criteria explained in 2-3 sentences]
  H2: Quick Comparison Table
    [Feature/price comparison table for all products]
  H2: #1. [Product A] — Best Overall
    H3: Key Features
    H3: Pricing
    H3: Pros and Cons
    H3: Best For
  H2: #2. [Product B] — Best Value
    [Same substructure]
  H2: #3. [Product C] — Best for Beginners
    [Same substructure]
  [... continue for 5-8 products ...]
  H2: How We Evaluated
    [Methodology section — builds trust]
  H2: How to Choose the Right Email Marketing Tool
    [Decision framework: if X, choose Y]
  H2: Frequently Asked Questions
```

### Example 3: Transactional — Pricing Query

**Query:** "project management software pricing"

```
H1: Project Management Software Pricing: Complete Breakdown ([Year])
  [Summary: price ranges from $X to $Y per user/month]
  H2: Pricing Comparison Table
    [Comprehensive table: product, free tier, starter, pro, enterprise]
  H2: [Product A] Pricing
    H3: Plans and Features
    H3: Hidden Costs to Watch
  H2: [Product B] Pricing
    [Same substructure]
  H2: [Product C] Pricing
    [Same substructure]
  H2: What Affects Pricing?
    [User count, features, integrations, support tier]
  H2: Free vs Paid: When to Upgrade
  H2: How to Negotiate Enterprise Pricing
  H2: Frequently Asked Questions
```

---

## Related Files

- [SKILL.md](SKILL.md) — Full content strategy guide with intent classification overview
- [KEYWORD_RESEARCH_GUIDE.md](KEYWORD_RESEARCH_GUIDE.md) — Grouping and filtering keywords by intent (Step 6)
- [CONTENT_CLUSTER_TEMPLATES.md](CONTENT_CLUSTER_TEMPLATES.md) — Cluster templates with format recommendations matched to intent
