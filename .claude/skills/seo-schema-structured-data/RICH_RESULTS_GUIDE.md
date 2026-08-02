# Rich Results Guide

Which structured data types trigger which rich results in Google Search, how to qualify, and how to monitor performance.

---

## Schema Type to Rich Result Mapping

| Schema Type | Rich Result Appearance | Where It Appears |
|-------------|----------------------|------------------|
| Article / BlogPosting | Article card with headline, image, date, author | Top Stories carousel, Discover feed, standard results |
| Product | Price, availability, star rating, review count below the link | Shopping results, standard organic results |
| FAQPage | Expandable accordion of Q&A pairs directly in the SERP | Standard organic results (up to 2 Q&A shown by default) |
| HowTo | Numbered steps with images, expandable in SERP | Standard organic results, Google Assistant |
| LocalBusiness | Enhanced knowledge panel with hours, address, phone, map | Local pack, knowledge panel, Maps |
| Organization | Logo, knowledge panel with social links and description | Knowledge panel on branded queries |
| BreadcrumbList | Breadcrumb trail replaces the green URL path | All organic result types |
| WebSite + SearchAction | Sitelinks search box on branded queries | Sitelinks section below branded results |
| Event | Date, location, ticket info in a card or carousel | Event listings, standard results |
| Recipe | Image, star rating, cook time, calorie count in a card | Recipe carousel, standard results, Google Images |
| VideoObject | Video thumbnail with duration badge and upload date | Video carousel, standard results, Google Video |
| Course | Course name, provider, description in a list | Course carousel, education results |
| SoftwareApplication | Star rating, price, category below the link | Standard organic results |
| JobPosting | Job title, salary, location, company in Google for Jobs | Google for Jobs experience (separate from organic) |
| Review | Star rating snippet below the link | Standard organic results |

---

## Rich Result Descriptions

### Article Rich Result
Displays a card with the article headline, featured image, publication date, and author name. Appears in the Top Stories carousel for news content and in the Discover feed on mobile. BlogPosting and NewsArticle both qualify.

### Product Rich Result
Shows price, currency, availability status (In Stock / Out of Stock), and star rating with review count directly below the search result link. Makes product pages significantly more prominent against competitors without markup.

### FAQ Rich Result
Renders as an expandable accordion within the search result. Users can click to expand individual questions and read answers without visiting the page. Google typically shows 2-4 questions. The expanded answers can include formatted HTML (bold text, links, lists).

### HowTo Rich Result
Displays step-by-step instructions with optional images for each step. Can appear as an expandable card or a carousel. Also surfaces in Google Assistant for voice queries. Steps must be clearly defined and match visible page content.

### Local Panel / Local Pack
LocalBusiness schema feeds data into the local knowledge panel and map pack. Shows business hours, address, phone number, photos, reviews, and a map pin. This is distinct from Google Business Profile but complements it.

### Organization Knowledge Panel
Displays the organization logo, description, social media links, and contact information in a knowledge panel on branded search queries. The `sameAs` property drives the social profile links.

### Breadcrumb Trail
Replaces the default green URL path below the page title with a structured breadcrumb trail (e.g., Home > Blog > SEO Guides). Improves click-through by showing the page hierarchy clearly.

### Sitelinks Search Box
Adds a search box directly within the sitelinks section of a branded query result. Users can search the site without visiting it first. Only appears for sites that Google deems authoritative enough for sitelinks.

### Event Listing
Shows event name, date, location, and ticket pricing in a card or carousel format. Events can also appear in a dedicated Events section on Google Search. Supports physical, virtual, and hybrid events.

### Recipe Card
Displays a rich card with recipe image, star rating, cook time, calorie count, and the recipe name. Appears in a dedicated recipe carousel at the top of recipe-related searches and in Google Images with structured overlays.

### Video Rich Result
Shows a video thumbnail with a play button overlay, duration badge, and upload date. Appears in a video carousel or inline in organic results. Videos with structured data are eligible for key moments (chapter markers).

### Course Listing
Displays in a course carousel showing the course name, provider institution, and a short description. Appears for education-related queries. Pricing and enrollment information may also display.

### Software Application
Shows star rating, price, and operating system information below the search result link. Particularly effective for app and tool review/comparison pages.

### Job Posting (Google for Jobs)
Appears in the Google for Jobs experience, a dedicated job search interface separate from standard organic results. Shows job title, company, location, salary range, and posting date. Users can filter by type, location, and date.

---

## Eligibility Requirements Per Rich Result

| Rich Result | Key Eligibility Requirements |
|-------------|------------------------------|
| Article | Must be a news, blog, or sports article page. Requires `headline`, `image`, `datePublished`, and `author` with `name` and `url`. |
| Product | Page must be about a specific product. Requires `name`, `image`, and `offers` with pricing. Reviews must be real. |
| FAQ | Page's primary purpose must be a list of questions and answers. All Q&As must be visible on the page. Not for forums. |
| HowTo | Page must contain step-by-step instructions. All steps visible on page. Not for recipe content (use Recipe instead). |
| Local Panel | Business must have a physical location. Address must be complete and accurate. Should align with Google Business Profile. |
| Organization | Must represent a real organization. Logo must meet minimum size (112x112px). |
| Breadcrumbs | Pages must have a logical hierarchy. Positions must be sequential integers starting at 1. |
| Sitelinks Search | Site must have a working internal search function. Google must deem the site eligible for sitelinks. |
| Event | Must be a real, upcoming event with a specific date. Must not be a coupon, voucher, or ongoing sale. |
| Recipe | Must be a recipe page with ingredients and instructions. Not for restaurant menus or food blogs without recipes. |
| Video | Video must be publicly accessible and the page must be the primary host. Thumbnail must be crawlable. |
| Course | Must be an educational course offered by a recognized provider. Not for individual lectures or blog posts. |
| Software | Must be about a specific software product. Requires pricing (use `0` for free apps). |
| Job Posting | Must be for a real, currently open position. Must include location and hiring company. Expires when `validThrough` passes. |

---

## Monitoring with Google Search Console

### Enhancements Report

**Path:** Google Search Console > Enhancements

Each structured data type you have implemented gets its own report section:

| Report Section | What It Shows |
|---------------|--------------|
| Valid items | Pages with correct, complete structured data |
| Valid with warnings | Pages that qualify but have missing recommended properties |
| Errors | Pages with broken or incomplete required properties |
| Total impressions | How often your rich results appeared in search |

### Key Metrics to Track

- **Error count trend** -- should decrease over time as you fix issues
- **Valid items count** -- should match the number of pages you expect to have schema
- **Coverage gaps** -- pages that should have schema but do not appear in the report
- **New errors after deployment** -- check within 48 hours of any schema or template change

### Using the URL Inspection Tool

1. Enter a specific URL in Search Console.
2. Click "Test Live URL" to see how Google renders the page.
3. Check the "Structured Data" section for detected types and any errors.
4. Compare against the cached version to spot rendering issues with JavaScript-injected schema.

---

## Common Reasons Rich Results Do Not Appear

| Reason | Details | Resolution |
|--------|---------|------------|
| Missing required properties | Schema is incomplete | Add all required properties per type (see VALIDATION_RULES.md) |
| Page not indexed | Google has not crawled the page | Submit URL via Search Console URL Inspection |
| Manual action | Spam policy violation penalized the site | Check Search Console > Security & Manual Actions |
| Content mismatch | Schema data differs from visible page content | Align schema properties with on-page content |
| Low site authority | Google may not show rich results for newer or low-authority sites | Build site authority over time; no shortcut |
| JavaScript rendering issues | Schema injected via JS is not being parsed | Test with URL Inspection "Live Test" to confirm rendering |
| Duplicate schemas | Conflicting schema blocks on the same page | Consolidate into one authoritative block per entity |
| Google algorithm choice | Google may choose not to display a rich result even when eligible | No fix; Google makes the final display decision |
| Schema type not supported | Using a type or property Google does not recognize for rich results | Use only Google-documented types (see SKILL.md) |
| robots.txt blocking | Images or pages referenced in schema are blocked from Googlebot | Ensure all schema-referenced resources are crawlable |
| Expired data | Event past `endDate`, job past `validThrough` | Remove or update expired structured data |

---

## Rich Result Types by Page Category

Use this table to decide which schema types to implement based on your page type.

| Page Category | Primary Schema | Additional Schema |
|--------------|---------------|-------------------|
| Blog post | Article / BlogPosting | BreadcrumbList, FAQPage (if Q&A content present), Person (author) |
| Product page | Product | BreadcrumbList, Review, Organization |
| Recipe page | Recipe | BreadcrumbList, VideoObject (if video present) |
| Event page | Event | BreadcrumbList, Organization (organizer) |
| Course page | Course | BreadcrumbList, Organization (provider) |
| Job listing | JobPosting | BreadcrumbList, Organization (employer) |
| Homepage | Organization, WebSite | BreadcrumbList (single-item: Home) |
| About page | Organization, Person | BreadcrumbList |
| Contact page | Organization, LocalBusiness | BreadcrumbList |
| FAQ page | FAQPage | BreadcrumbList, Organization |
| How-to guide | HowTo | BreadcrumbList, Article, VideoObject |
| Video page | VideoObject | BreadcrumbList, Article |
| App/tool page | SoftwareApplication | BreadcrumbList, Organization |
| Category/listing | CollectionPage (no rich result) | BreadcrumbList |
| Author page | Person | BreadcrumbList |

---

## Quick Decision Flowchart

1. **Does the page have a clear entity type?** (product, article, event, recipe, etc.)
   - Yes: Implement the matching primary schema type.
   - No: Implement BreadcrumbList + Organization at minimum.

2. **Does the page have hierarchical navigation?**
   - Yes: Add BreadcrumbList.

3. **Does the page contain FAQ content?**
   - Yes: Add FAQPage in addition to the primary type.

4. **Is there a video on the page?**
   - Yes: Add VideoObject.

5. **Is this the homepage?**
   - Yes: Add Organization + WebSite (with SearchAction if site has search).

**MCP Tool:** Use `extract_schema` on competitor pages to see which rich results they are targeting, then use `generate_schema` to create matching or superior markup for your pages.
