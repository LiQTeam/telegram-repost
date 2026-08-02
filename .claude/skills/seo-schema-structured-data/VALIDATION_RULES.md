# Structured Data Validation Rules

Google's requirements, constraints, and testing workflow for structured data markup.

---

## Required Properties by Type

If any required property is missing, Google will not generate a rich result for that type.

| Schema Type | Required Properties |
|-------------|-------------------|
| Article / BlogPosting | `headline`, `image`, `datePublished`, `author.name` |
| Product | `name`, `image`, `offers` (with `price`, `priceCurrency`, `availability`) |
| FAQPage | `mainEntity` (array of Question), each with `name` and `acceptedAnswer.text` |
| HowTo | `name`, `step` (array of HowToStep, each with `name` or `text`) |
| LocalBusiness | `name`, `address` (PostalAddress) |
| Organization | `name`, `url`, `logo` |
| BreadcrumbList | `itemListElement` (array of ListItem with `position`, `name`, `item`) |
| WebSite | `url`, `potentialAction` (SearchAction with `target` and `query-input`) |
| Event | `name`, `startDate`, `location` (Place with `name` and `address`) |
| Recipe | `name`, `image`, `author`, `recipeInstructions` |
| VideoObject | `name`, `description`, `thumbnailUrl`, `uploadDate` |
| Course | `name`, `description`, `provider` (Organization) |
| SoftwareApplication | `name`, `offers` (with `price`, `priceCurrency`) |
| JobPosting | `title`, `description`, `datePosted`, `hiringOrganization`, `jobLocation` |
| Review | `itemReviewed`, `author`, `reviewRating.ratingValue` |

---

## Recommended Properties by Type

Including recommended properties increases the chance of richer, more prominent search appearances.

| Schema Type | Recommended Properties |
|-------------|----------------------|
| Article | `dateModified`, `publisher`, `description`, `mainEntityOfPage`, `wordCount` |
| Product | `description`, `sku`, `brand`, `aggregateRating`, `review`, `gtin13`, `mpn` |
| FAQPage | Additional Question entries (more Q&As = more real estate) |
| HowTo | `totalTime`, `estimatedCost`, `supply`, `tool`, `step.image`, `step.url` |
| LocalBusiness | `telephone`, `openingHoursSpecification`, `geo`, `priceRange`, `image`, `aggregateRating` |
| Organization | `sameAs`, `contactPoint`, `address`, `description`, `foundingDate` |
| BreadcrumbList | (All core properties are required; no additional recommended) |
| WebSite | `name`, `description`, `publisher` |
| Event | `endDate`, `description`, `image`, `offers`, `performer`, `organizer`, `eventStatus`, `eventAttendanceMode` |
| Recipe | `prepTime`, `cookTime`, `totalTime`, `recipeYield`, `recipeIngredient`, `nutrition`, `aggregateRating`, `video` |
| VideoObject | `contentUrl`, `embedUrl`, `duration`, `interactionStatistic` |
| Course | `offers`, `hasCourseInstance`, `courseCode`, `educationalLevel` |
| SoftwareApplication | `operatingSystem`, `applicationCategory`, `aggregateRating`, `screenshot` |
| JobPosting | `validThrough`, `employmentType`, `baseSalary`, `jobLocationType`, `directApply` |

---

## Value Constraints

### String Lengths

| Property | Constraint |
|----------|-----------|
| `headline` (Article) | Max 110 characters |
| `name` (general) | No hard limit, but keep under 200 characters |
| `description` | No hard limit, but 50-300 characters recommended |
| `Answer.text` (FAQ) | No limit; HTML is permitted (bold, links, lists) |
| `reviewBody` | No hard limit |

### Date Formats (ISO 8601)

All date properties must use ISO 8601 format:

| Format | Example | Use For |
|--------|---------|---------|
| Date only | `2025-03-15` | `datePublished`, `datePosted`, `foundingDate` |
| Date + time + timezone | `2025-03-15T08:00:00+00:00` | `startDate`, `endDate`, `validThrough` |
| Date + time + Z (UTC) | `2025-03-15T08:00:00Z` | Any datetime property |

**Invalid formats:** `03/15/2025`, `March 15, 2025`, `15-03-2025`

### Duration Format (ISO 8601)

Used for `totalTime`, `prepTime`, `cookTime`, `duration`:

| Duration | ISO 8601 |
|----------|----------|
| 30 minutes | `PT30M` |
| 1 hour 15 minutes | `PT1H15M` |
| 2 hours | `PT2H` |
| 45 seconds | `PT45S` |
| 12 weeks | `PT12W` |

### URL Requirements

| Rule | Details |
|------|---------|
| Protocol | Must use `https://` (not `http://`) |
| Format | Fully qualified, absolute URLs (not relative paths) |
| Validity | URLs must resolve (no 404s, no redirect chains) |
| Images | Must be crawlable by Googlebot (not blocked by robots.txt) |
| Canonical | URL in schema should match the canonical URL of the page |

### Enum Values

**availability** (Offer):
| Value | Meaning |
|-------|---------|
| `https://schema.org/InStock` | Available for purchase |
| `https://schema.org/OutOfStock` | Not currently available |
| `https://schema.org/PreOrder` | Available for pre-order |
| `https://schema.org/SoldOut` | Permanently sold out |
| `https://schema.org/Discontinued` | No longer manufactured |
| `https://schema.org/BackOrder` | Available on back-order |

**itemCondition** (Offer):
| Value | Meaning |
|-------|---------|
| `https://schema.org/NewCondition` | Brand new |
| `https://schema.org/RefurbishedCondition` | Refurbished |
| `https://schema.org/UsedCondition` | Used/pre-owned |
| `https://schema.org/DamagedCondition` | Damaged |

**eventStatus** (Event):
| Value | Meaning |
|-------|---------|
| `https://schema.org/EventScheduled` | Taking place as planned |
| `https://schema.org/EventCancelled` | Cancelled |
| `https://schema.org/EventPostponed` | Postponed (date TBD) |
| `https://schema.org/EventRescheduled` | Moved to a new date |
| `https://schema.org/EventMovedOnline` | Changed to virtual |

**eventAttendanceMode** (Event):
| Value | Meaning |
|-------|---------|
| `https://schema.org/OfflineEventAttendanceMode` | In-person only |
| `https://schema.org/OnlineEventAttendanceMode` | Virtual only |
| `https://schema.org/MixedEventAttendanceMode` | Hybrid |

**employmentType** (JobPosting):
`FULL_TIME`, `PART_TIME`, `CONTRACTOR`, `TEMPORARY`, `INTERN`, `VOLUNTEER`, `PER_DIEM`, `OTHER`

---

## Content-Visibility Consistency Requirements

Google requires that structured data accurately reflects content visible to users on the page.

| Rule | Description |
|------|-------------|
| Visible content match | Every property in structured data must correspond to content the user can see on the page |
| Price accuracy | The price in Product schema must match the price displayed on the page |
| Rating accuracy | AggregateRating values must reflect real, displayed user reviews |
| Image relevance | Images referenced in schema must appear on the page or directly relate to the content |
| Author attribution | The author in Article schema must be visibly credited on the page |
| FAQ visibility | Every question and answer in FAQPage markup must be visible on the page |
| Step visibility | Every HowTo step must be visible as instructional content on the page |
| Date accuracy | Published/modified dates must match what is shown to users |

---

## Spam Policies

Violations can result in manual actions (penalties) in Google Search Console.

| Violation | Description |
|-----------|-------------|
| Hidden content markup | Marking up content that is invisible to users (display:none, hidden elements) |
| Fake reviews | Using fabricated ratings, reviews, or inflated review counts |
| Irrelevant markup | Adding schema types that do not match the page content (e.g., Product schema on a blog post) |
| Misleading content | Structured data that describes different content than what the page shows |
| Keyword stuffing | Overloading schema text fields with irrelevant keywords |
| Duplicate entities | Multiple conflicting schema blocks for the same entity on one page |
| Automated fake data | Using scripts to generate fake review counts or ratings |
| Marked-up ads | Applying Product or Review schema to sponsored/ad content without disclosure |

**Google's policy summary:** Structured data must provide an accurate, complete, and non-deceptive representation of the page content. Pages that violate structured data guidelines may receive a manual action that removes rich result eligibility.

---

## Common Validation Errors and Fixes

| Error | Cause | Fix |
|-------|-------|-----|
| `Missing field "image"` | No image property on Article or Product | Add at least one valid image URL |
| `Missing field "author"` | Article lacks author | Add `author` with `@type: Person` and `name` |
| `Missing field "name"` | Entity has no name property | Add the `name` property with real content |
| `Invalid value for "price"` | Price is non-numeric or missing | Use a numeric string: `"29.99"` (not `"$29.99"` or `"Free"`) |
| `Invalid URL in "image"` | Relative URL or HTTP protocol | Use absolute HTTPS URL |
| `Invalid date format` | Non-ISO date string | Convert to `YYYY-MM-DD` or `YYYY-MM-DDTHH:MM:SS+00:00` |
| `"availability" value is invalid` | Custom string instead of schema.org enum | Use full schema.org URL: `https://schema.org/InStock` |
| `Incorrect "position" value` | BreadcrumbList positions not sequential | Use integers starting at 1 and incrementing by 1 |
| `"@type" is not recognized` | Typo in type name or unsupported type | Check spelling against schema.org vocabulary |
| `Missing required "offers"` | Product or SoftwareApplication without pricing | Add Offer object with price and priceCurrency |
| `Multiple entities conflict` | Two Product schemas with different prices | Consolidate into one authoritative schema block |
| `Warning: "description" missing` | Recommended property absent | Add description to improve rich result eligibility |
| `Warning: "dateModified" missing` | Article only has datePublished | Add dateModified to signal freshness |

---

## Testing Workflow

### Step 1: Rich Results Test (Google)

**URL:** https://search.google.com/test/rich-results

- Paste a URL or code snippet.
- Shows which rich results the page is eligible for.
- Reports **errors** (blocks rich results) and **warnings** (reduces eligibility).
- Always test after any schema change.

### Step 2: Schema Markup Validator (Schema.org)

**URL:** https://validator.schema.org/

- Validates against the full Schema.org vocabulary.
- Catches structural issues that Google's tool may not flag.
- Useful for catching `@id` reference mismatches and incorrect nesting.

### Step 3: Google Search Console

**Path:** Search Console > Enhancements

- Monitor structured data performance at scale.
- View error/warning/valid counts per schema type.
- Track which pages have issues and when they were detected.
- Review after deploying schema changes to confirm indexing.

### Step 4: Live URL Inspection

**Path:** Search Console > URL Inspection > Test Live URL

- Tests how Googlebot renders and parses your page in real time.
- Confirms that dynamically injected JSON-LD (via JavaScript) is readable.
- Shows the rendered HTML that Google sees.

### Recommended Testing Cadence

| Event | Action |
|-------|--------|
| New schema added | Test immediately with Rich Results Test |
| Schema template changed | Re-test all affected page types |
| CMS or platform update | Spot-check 5-10 pages across types |
| Weekly | Review Search Console Enhancements for new errors |
| Monthly | Full audit of all schema types in Search Console |

**MCP Tool:** Use `extract_schema` to pull the live structured data from any URL and compare it against these validation rules. Use `generate_schema` to produce markup that passes all required-field checks.
