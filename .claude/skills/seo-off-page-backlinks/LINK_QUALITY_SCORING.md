# Link Quality Scoring Model

A systematic framework for evaluating individual backlinks on a 1-10 scale across six dimensions.

---

## Overview

Every backlink can be scored using six dimensions. Each dimension receives a score from 1 to 10, then the weighted average produces an overall Link Quality Score (LQS).

**Formula:**

```
LQS = (Domain Authority * 0.20) + (Relevance * 0.25) + (Placement * 0.15)
    + (Anchor Text * 0.15) + (Traffic * 0.15) + (Trust * 0.10)
```

---

## Dimension 1: Domain Authority (Weight: 20%)

Measures the overall link equity strength of the referring domain.

| Score | DR/DA Range | Description |
|-------|-------------|-------------|
| 10 | 80-100 | Elite domains (NYT, BBC, .gov, .edu, Wikipedia) |
| 9 | 70-79 | Major brands, top-tier publications |
| 8 | 60-69 | Well-known industry sites, large media outlets |
| 7 | 50-59 | Established businesses, popular niche publications |
| 6 | 40-49 | Solid mid-tier sites with real audiences |
| 5 | 30-39 | Moderate authority, smaller but legitimate |
| 4 | 20-29 | Low authority, newer or smaller sites |
| 3 | 10-19 | Very low authority, limited link profile |
| 2 | 5-9 | Barely any authority, minimal backlinks |
| 1 | 0-4 | No authority, new/spammy/parked domain |

---

## Dimension 2: Relevance (Weight: 25%)

Measures how topically related the linking site and page are to your content. This is the most important dimension.

| Score | Relevance Level | Description |
|-------|----------------|-------------|
| 10 | Exact topic match | Same niche, same subtopic, same target audience |
| 9 | Same niche | Same industry, closely related subtopic |
| 8 | Related niche | Adjacent industry with significant audience overlap |
| 7 | Broad relevance | General business/tech site covering your vertical |
| 6 | Partial relevance | The specific page is relevant even if the site is broad |
| 5 | Tangential | Loosely related through a shared theme |
| 4 | Weak relevance | General site, the link is in a somewhat related context |
| 3 | Mostly irrelevant | Different industry, only vague topical connection |
| 2 | Irrelevant | No topical relationship, different audience entirely |
| 1 | Harmful irrelevance | Unrelated foreign-language site, adult/gambling/pharma (if not your niche) |

---

## Dimension 3: Placement (Weight: 15%)

Measures where the link appears on the page and how it is integrated into the content.

| Score | Placement | Description |
|-------|-----------|-------------|
| 10 | Editorial in-content (top half) | Contextual link within the main body, above the fold |
| 9 | Editorial in-content (any position) | Contextual link within the main body text |
| 8 | Prominent resource list | Featured in a curated "best of" or resource roundup |
| 7 | Author bio (relevant guest post) | Earned through contributed expert content |
| 6 | Inline resource mention | Listed among recommended tools/resources within content |
| 5 | Sidebar feature or callout box | Visible but not in-content |
| 4 | Footer of a relevant article | End-of-article resources section |
| 3 | Site-wide sidebar widget | Appears on every page in sidebar (diluted value) |
| 2 | Site-wide footer link | Appears in footer across all pages |
| 1 | Hidden, comment, or injected | Comment section, hidden text, or inserted via hack |

---

## Dimension 4: Anchor Text (Weight: 15%)

Measures the quality and naturalness of the anchor text used for the link.

| Score | Anchor Type | Description |
|-------|-------------|-------------|
| 10 | Descriptive partial-match | Natural sentence containing target keyword variation |
| 9 | Branded + keyword | Brand name combined with relevant keyword |
| 8 | Branded | Clean brand mention as anchor |
| 7 | Natural descriptive phrase | Describes the destination accurately without keywords |
| 6 | Naked URL | Raw URL used as anchor text |
| 5 | Generic with context | "this guide" or "learn more" within a relevant sentence |
| 4 | Pure generic | "click here", "read more" with no surrounding context |
| 3 | Exact-match keyword | Exact target keyword (acceptable in moderation) |
| 2 | Over-optimized exact-match | Exact keyword in an unnatural or forced sentence |
| 1 | Spammy or irrelevant | Keyword-stuffed, foreign text, or clearly manipulated |

**Note:** Exact-match anchors score lower because they carry higher penalty risk when overused. A few are fine; a pattern of many is dangerous.

---

## Dimension 5: Traffic (Weight: 15%)

Measures whether the linking page actually receives organic visitors.

| Score | Monthly Organic Traffic | Description |
|-------|------------------------|-------------|
| 10 | 10,000+ visits/month | High-traffic page sending real referral visitors |
| 9 | 5,000-9,999 | Strong traffic, meaningful referral potential |
| 8 | 2,000-4,999 | Good traffic, page ranks well for its keywords |
| 7 | 1,000-1,999 | Moderate traffic, page has some SERP visibility |
| 6 | 500-999 | Some traffic, page is indexed and ranking |
| 5 | 200-499 | Light traffic, but page is active and crawled |
| 4 | 50-199 | Minimal traffic, page exists but barely ranks |
| 3 | 10-49 | Very low traffic, limited SERP presence |
| 2 | 1-9 | Near-zero traffic, essentially invisible |
| 1 | 0 | No traffic — dead page, deindexed, or never indexed |

---

## Dimension 6: Trust (Weight: 10%)

Measures trust signals and spam risk of the referring domain.

| Score | Trust Level | Description |
|-------|-------------|-------------|
| 10 | Government or educational institution | .gov, .edu, verified institutions |
| 9 | Major verified brand or news outlet | Real business with strong reputation |
| 8 | Established business with real presence | Physical address, social profiles, reviews |
| 7 | Known niche authority | Recognized by the community, cited by others |
| 6 | Legitimate small business or blog | Real author, consistent publishing, some social presence |
| 5 | Anonymous but legitimate | No clear author but content is original and useful |
| 4 | Questionable quality | Thin content, excessive ads, but not overtly spammy |
| 3 | Spam signals present | Excessive outbound links, low-quality content |
| 2 | Likely PBN or link farm | Interlinked network patterns, fake content |
| 1 | Known spam, malware, or hacked | Flagged by security tools, manual action history |

---

## Quality Tiers

After calculating the weighted LQS, classify each backlink:

| Tier | LQS Range | Label | Action |
|------|-----------|-------|--------|
| Tier 1 | 8.0 - 10.0 | **Premium** | Protect and nurture this relationship. These are your most valuable links. |
| Tier 2 | 5.0 - 7.9 | **Good** | Solid links that contribute positively. No action needed. |
| Tier 3 | 3.0 - 4.9 | **Low Quality** | Weak but generally harmless. Monitor but do not disavow. |
| Tier 4 | 1.0 - 2.9 | **Toxic / Harmful** | Evaluate for disavow. Request removal if possible. |

---

## Scoring Examples

### Example 1: Premium Link (LQS 9.1)

A cybersecurity blog receives a link from a TechCrunch article about data breaches.

| Dimension | Score | Reasoning |
|-----------|-------|-----------|
| Domain Authority | 10 | TechCrunch DR 92 |
| Relevance | 9 | Same industry (tech/security), closely related topic |
| Placement | 9 | In-content editorial link within the article body |
| Anchor Text | 10 | "detailed analysis of the breach patterns" (descriptive partial-match) |
| Traffic | 10 | Article receives 15,000+ monthly visits |
| Trust | 9 | Major verified publication |
| **Weighted LQS** | **9.5** | **Premium tier** |

### Example 2: Good Link (LQS 6.3)

A local bakery receives a link from a regional food blog's "Best Bakeries in Austin" roundup.

| Dimension | Score | Reasoning |
|-----------|-------|-----------|
| Domain Authority | 4 | Food blog DR 25 |
| Relevance | 10 | Exact niche and location match |
| Placement | 8 | Featured in curated "best of" list |
| Anchor Text | 8 | Branded anchor ("Sweet Flour Bakery") |
| Traffic | 5 | ~300 monthly visits |
| Trust | 6 | Legitimate blog with real author and social presence |
| **Weighted LQS** | **6.8** | **Good tier** |

### Example 3: Toxic Link (LQS 1.8)

A SaaS company finds a link from a foreign-language directory with 500+ outbound links per page.

| Dimension | Score | Reasoning |
|-----------|-------|-----------|
| Domain Authority | 2 | DR 7, barely any real backlinks of its own |
| Relevance | 1 | Russian-language general directory, no niche relation |
| Placement | 2 | Sitewide footer link appearing on every page |
| Anchor Text | 1 | Exact-match keyword anchor in English on a Russian page |
| Traffic | 1 | Zero organic traffic |
| Trust | 1 | Spam signals: excessive OBLs, thin content, no real business |
| **Weighted LQS** | **1.3** | **Toxic tier -- disavow** |

---

## Using the Scoring Model

1. **Export your backlink profile** using `analyze_backlinks`
2. **Score a representative sample** (top 50-100 referring domains by traffic/authority)
3. **Flag all Tier 4 links** for potential disavow action
4. **Identify Tier 1 links** to understand what is working and replicate
5. **Calculate your profile distribution** -- a healthy site has 60%+ links in Tier 1-2
6. **Compare against competitors** to identify quality gaps

### Healthy Profile Distribution

| Tier | Healthy % | Risky % |
|------|-----------|---------|
| Premium (8-10) | 10-20% | <5% |
| Good (5-7.9) | 50-65% | <30% |
| Low (3-4.9) | 15-25% | >40% |
| Toxic (1-2.9) | <5% | >15% |
