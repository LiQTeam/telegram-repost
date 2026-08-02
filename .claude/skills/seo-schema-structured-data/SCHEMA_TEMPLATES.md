# JSON-LD Schema Templates

Ready-to-use, valid JSON-LD templates for every major Google-supported structured data type. Copy, customize, and inject into your pages.

---

## 1. Article / BlogPosting

```json
{
  "@context": "https://schema.org",
  "@type": "BlogPosting",
  "headline": "10 Tips for Better On-Page SEO in 2025",
  "description": "Learn the most effective on-page SEO techniques to boost your search rankings and drive organic traffic.",
  "image": [
    "https://example.com/images/seo-tips-1x1.jpg",
    "https://example.com/images/seo-tips-4x3.jpg",
    "https://example.com/images/seo-tips-16x9.jpg"
  ],
  "datePublished": "2025-03-15T08:00:00+00:00",
  "dateModified": "2025-06-01T10:30:00+00:00",
  "author": {
    "@type": "Person",
    "name": "Sarah Johnson",
    "url": "https://example.com/authors/sarah-johnson"
  },
  "publisher": {
    "@type": "Organization",
    "name": "SEO Weekly",
    "logo": {
      "@type": "ImageObject",
      "url": "https://example.com/logo.png",
      "width": 600,
      "height": 60
    }
  },
  "mainEntityOfPage": {
    "@type": "WebPage",
    "@id": "https://example.com/blog/on-page-seo-tips"
  },
  "wordCount": 2500,
  "articleSection": "SEO",
  "keywords": ["on-page SEO", "search optimization", "meta tags"]
}
```

> Change `@type` to `"NewsArticle"` for news content or `"Article"` for generic articles.

---

## 2. Product (with Offer and AggregateRating)

```json
{
  "@context": "https://schema.org",
  "@type": "Product",
  "name": "Ergonomic Standing Desk Pro",
  "image": [
    "https://example.com/images/desk-front.jpg",
    "https://example.com/images/desk-side.jpg"
  ],
  "description": "Height-adjustable standing desk with programmable memory settings, cable management, and bamboo tabletop. Fits desktops up to 72 inches.",
  "sku": "DESK-PRO-72",
  "gtin13": "0012345678905",
  "mpn": "DSK72PRO",
  "brand": {
    "@type": "Brand",
    "name": "ErgoWorks"
  },
  "offers": {
    "@type": "Offer",
    "url": "https://example.com/products/standing-desk-pro",
    "price": "549.99",
    "priceCurrency": "USD",
    "priceValidUntil": "2025-12-31",
    "availability": "https://schema.org/InStock",
    "itemCondition": "https://schema.org/NewCondition",
    "seller": {
      "@type": "Organization",
      "name": "ErgoWorks Official Store"
    },
    "shippingDetails": {
      "@type": "OfferShippingDetails",
      "shippingRate": {
        "@type": "MonetaryAmount",
        "value": "0",
        "currency": "USD"
      },
      "deliveryTime": {
        "@type": "ShippingDeliveryTime",
        "handlingTime": {
          "@type": "QuantitativeValue",
          "minValue": 1,
          "maxValue": 2,
          "unitCode": "DAY"
        },
        "transitTime": {
          "@type": "QuantitativeValue",
          "minValue": 3,
          "maxValue": 7,
          "unitCode": "DAY"
        }
      },
      "shippingDestination": {
        "@type": "DefinedRegion",
        "addressCountry": "US"
      }
    }
  },
  "aggregateRating": {
    "@type": "AggregateRating",
    "ratingValue": "4.7",
    "bestRating": "5",
    "worstRating": "1",
    "ratingCount": "342",
    "reviewCount": "287"
  },
  "review": [
    {
      "@type": "Review",
      "author": {
        "@type": "Person",
        "name": "Mike Chen"
      },
      "datePublished": "2025-05-10",
      "reviewRating": {
        "@type": "Rating",
        "ratingValue": "5",
        "bestRating": "5"
      },
      "reviewBody": "Best standing desk I have ever owned. The memory presets are a game changer."
    }
  ]
}
```

---

## 3. FAQPage

```json
{
  "@context": "https://schema.org",
  "@type": "FAQPage",
  "mainEntity": [
    {
      "@type": "Question",
      "name": "What is structured data?",
      "acceptedAnswer": {
        "@type": "Answer",
        "text": "Structured data is a standardized format for providing information about a page and classifying its content. Search engines use it to understand page content and display rich results."
      }
    },
    {
      "@type": "Question",
      "name": "Does structured data improve rankings?",
      "acceptedAnswer": {
        "@type": "Answer",
        "text": "Structured data does not directly improve rankings, but it can earn rich results that increase click-through rate (CTR), which indirectly benefits SEO performance."
      }
    },
    {
      "@type": "Question",
      "name": "Which format should I use for structured data?",
      "acceptedAnswer": {
        "@type": "Answer",
        "text": "Google recommends <strong>JSON-LD</strong> as the preferred format. It is easier to implement and maintain compared to Microdata or RDFa because it is decoupled from the HTML markup."
      }
    }
  ]
}
```

---

## 4. HowTo

```json
{
  "@context": "https://schema.org",
  "@type": "HowTo",
  "name": "How to Add JSON-LD Structured Data to Your Website",
  "description": "Step-by-step guide to implementing JSON-LD structured data on any website for better search visibility.",
  "totalTime": "PT20M",
  "estimatedCost": {
    "@type": "MonetaryAmount",
    "currency": "USD",
    "value": "0"
  },
  "tool": [
    {
      "@type": "HowToTool",
      "name": "Text editor or CMS"
    },
    {
      "@type": "HowToTool",
      "name": "Google Rich Results Test"
    }
  ],
  "step": [
    {
      "@type": "HowToStep",
      "name": "Choose the schema type",
      "text": "Determine which Schema.org type matches your page content. For a blog post use Article, for a product page use Product, etc.",
      "url": "https://example.com/guide/json-ld#step-1",
      "image": "https://example.com/images/step1-choose-type.jpg"
    },
    {
      "@type": "HowToStep",
      "name": "Write the JSON-LD markup",
      "text": "Create a JSON object with @context set to https://schema.org, @type set to your chosen type, and fill in all required properties with real data from your page.",
      "url": "https://example.com/guide/json-ld#step-2",
      "image": "https://example.com/images/step2-write-json.jpg"
    },
    {
      "@type": "HowToStep",
      "name": "Inject the script tag",
      "text": "Wrap your JSON-LD in a script tag with type application/ld+json and place it in the head or body of your HTML page.",
      "url": "https://example.com/guide/json-ld#step-3",
      "image": "https://example.com/images/step3-inject-script.jpg"
    },
    {
      "@type": "HowToStep",
      "name": "Validate with Rich Results Test",
      "text": "Open https://search.google.com/test/rich-results and enter your page URL or paste the code snippet. Fix any errors or warnings that appear.",
      "url": "https://example.com/guide/json-ld#step-4",
      "image": "https://example.com/images/step4-validate.jpg"
    }
  ]
}
```

---

## 5. LocalBusiness (Restaurant Example)

```json
{
  "@context": "https://schema.org",
  "@type": "Restaurant",
  "name": "Bella Napoli Trattoria",
  "image": "https://example.com/images/bella-napoli-exterior.jpg",
  "url": "https://www.bellanapoli.com",
  "telephone": "+1-212-555-0142",
  "priceRange": "$$",
  "servesCuisine": ["Italian", "Mediterranean"],
  "menu": "https://www.bellanapoli.com/menu",
  "acceptsReservations": "True",
  "address": {
    "@type": "PostalAddress",
    "streetAddress": "123 Mulberry Street",
    "addressLocality": "New York",
    "addressRegion": "NY",
    "postalCode": "10013",
    "addressCountry": "US"
  },
  "geo": {
    "@type": "GeoCoordinates",
    "latitude": 40.7195,
    "longitude": -73.9973
  },
  "openingHoursSpecification": [
    {
      "@type": "OpeningHoursSpecification",
      "dayOfWeek": ["Monday", "Tuesday", "Wednesday", "Thursday"],
      "opens": "11:00",
      "closes": "22:00"
    },
    {
      "@type": "OpeningHoursSpecification",
      "dayOfWeek": ["Friday", "Saturday"],
      "opens": "11:00",
      "closes": "23:00"
    },
    {
      "@type": "OpeningHoursSpecification",
      "dayOfWeek": "Sunday",
      "opens": "12:00",
      "closes": "21:00"
    }
  ],
  "aggregateRating": {
    "@type": "AggregateRating",
    "ratingValue": "4.6",
    "reviewCount": "523"
  }
}
```

---

## 6. Organization

```json
{
  "@context": "https://schema.org",
  "@type": "Organization",
  "@id": "https://example.com/#organization",
  "name": "Acme Digital Solutions",
  "url": "https://example.com",
  "logo": {
    "@type": "ImageObject",
    "url": "https://example.com/logo.png",
    "width": 300,
    "height": 300
  },
  "description": "Acme Digital Solutions provides SEO, web development, and digital marketing services to businesses worldwide.",
  "foundingDate": "2010-06-15",
  "founders": [
    {
      "@type": "Person",
      "name": "Alex Rivera"
    }
  ],
  "address": {
    "@type": "PostalAddress",
    "streetAddress": "456 Tech Drive, Suite 200",
    "addressLocality": "Austin",
    "addressRegion": "TX",
    "postalCode": "78701",
    "addressCountry": "US"
  },
  "contactPoint": {
    "@type": "ContactPoint",
    "telephone": "+1-512-555-0199",
    "contactType": "customer service",
    "availableLanguage": ["English", "Spanish"]
  },
  "sameAs": [
    "https://www.facebook.com/acmedigital",
    "https://twitter.com/acmedigital",
    "https://www.linkedin.com/company/acmedigital",
    "https://www.youtube.com/acmedigital"
  ]
}
```

---

## 7. BreadcrumbList

```json
{
  "@context": "https://schema.org",
  "@type": "BreadcrumbList",
  "itemListElement": [
    {
      "@type": "ListItem",
      "position": 1,
      "name": "Home",
      "item": "https://example.com/"
    },
    {
      "@type": "ListItem",
      "position": 2,
      "name": "Blog",
      "item": "https://example.com/blog/"
    },
    {
      "@type": "ListItem",
      "position": 3,
      "name": "SEO Guides",
      "item": "https://example.com/blog/seo-guides/"
    },
    {
      "@type": "ListItem",
      "position": 4,
      "name": "Structured Data Implementation"
    }
  ]
}
```

> The last ListItem omits `item` because it represents the current page.

---

## 8. WebSite (with SearchAction)

```json
{
  "@context": "https://schema.org",
  "@type": "WebSite",
  "@id": "https://example.com/#website",
  "url": "https://example.com/",
  "name": "Acme Digital Solutions",
  "description": "SEO tools, guides, and digital marketing resources.",
  "publisher": {
    "@id": "https://example.com/#organization"
  },
  "potentialAction": {
    "@type": "SearchAction",
    "target": {
      "@type": "EntryPoint",
      "urlTemplate": "https://example.com/search?q={search_term_string}"
    },
    "query-input": "required name=search_term_string"
  }
}
```

---

## 9. Event

```json
{
  "@context": "https://schema.org",
  "@type": "Event",
  "name": "BrightonSEO Conference 2025",
  "description": "The world's largest search marketing conference returns to Brighton with 100+ speakers covering SEO, PPC, and content marketing.",
  "startDate": "2025-10-02T09:00:00+01:00",
  "endDate": "2025-10-03T18:00:00+01:00",
  "eventStatus": "https://schema.org/EventScheduled",
  "eventAttendanceMode": "https://schema.org/OfflineEventAttendanceMode",
  "location": {
    "@type": "Place",
    "name": "Brighton Centre",
    "address": {
      "@type": "PostalAddress",
      "streetAddress": "King's Road",
      "addressLocality": "Brighton",
      "addressRegion": "East Sussex",
      "postalCode": "BN1 2GR",
      "addressCountry": "GB"
    }
  },
  "image": "https://example.com/images/brightonseo-2025.jpg",
  "offers": {
    "@type": "Offer",
    "url": "https://example.com/tickets",
    "price": "299.00",
    "priceCurrency": "GBP",
    "availability": "https://schema.org/InStock",
    "validFrom": "2025-04-01T00:00:00+01:00"
  },
  "performer": {
    "@type": "Person",
    "name": "Kelsey Jones"
  },
  "organizer": {
    "@type": "Organization",
    "name": "Rough Agenda Ltd",
    "url": "https://www.brightonseo.com"
  }
}
```

---

## 10. Recipe

```json
{
  "@context": "https://schema.org",
  "@type": "Recipe",
  "name": "Classic Margherita Pizza",
  "image": [
    "https://example.com/images/margherita-1x1.jpg",
    "https://example.com/images/margherita-4x3.jpg",
    "https://example.com/images/margherita-16x9.jpg"
  ],
  "author": {
    "@type": "Person",
    "name": "Chef Marco Rossi"
  },
  "datePublished": "2025-04-20",
  "description": "Authentic Neapolitan margherita pizza with San Marzano tomatoes, fresh mozzarella, basil, and a perfectly charred crust.",
  "prepTime": "PT30M",
  "cookTime": "PT10M",
  "totalTime": "PT40M",
  "recipeYield": "2 pizzas",
  "recipeCategory": "Main Course",
  "recipeCuisine": "Italian",
  "keywords": "pizza, margherita, Italian, Neapolitan",
  "nutrition": {
    "@type": "NutritionInformation",
    "calories": "266 calories",
    "fatContent": "10g",
    "carbohydrateContent": "33g",
    "proteinContent": "12g"
  },
  "recipeIngredient": [
    "500g Tipo 00 flour",
    "325ml warm water",
    "10g salt",
    "3g active dry yeast",
    "400g canned San Marzano tomatoes",
    "250g fresh mozzarella di bufala",
    "Fresh basil leaves",
    "Extra virgin olive oil"
  ],
  "recipeInstructions": [
    {
      "@type": "HowToStep",
      "name": "Make the dough",
      "text": "Combine flour, water, salt, and yeast. Knead for 10 minutes until smooth and elastic. Cover and let rise for 8-24 hours in the refrigerator."
    },
    {
      "@type": "HowToStep",
      "name": "Prepare the sauce",
      "text": "Crush San Marzano tomatoes by hand. Season with a pinch of salt. Do not cook the sauce."
    },
    {
      "@type": "HowToStep",
      "name": "Shape and top the pizza",
      "text": "Stretch the dough into a 12-inch round. Spread sauce, tear mozzarella over the top, and add fresh basil leaves."
    },
    {
      "@type": "HowToStep",
      "name": "Bake",
      "text": "Bake in a preheated oven at the highest temperature (250-300C / 480-570F) for 8-10 minutes until the crust is charred and bubbly."
    }
  ],
  "aggregateRating": {
    "@type": "AggregateRating",
    "ratingValue": "4.9",
    "ratingCount": "1204"
  },
  "video": {
    "@type": "VideoObject",
    "name": "How to Make Margherita Pizza",
    "description": "Watch Chef Marco make authentic Neapolitan margherita pizza from scratch.",
    "thumbnailUrl": "https://example.com/images/margherita-video-thumb.jpg",
    "uploadDate": "2025-04-20T08:00:00+00:00",
    "duration": "PT8M30S",
    "contentUrl": "https://example.com/videos/margherita-pizza.mp4"
  }
}
```

---

## 11. VideoObject

```json
{
  "@context": "https://schema.org",
  "@type": "VideoObject",
  "name": "Complete Guide to Technical SEO Audits",
  "description": "Learn how to perform a comprehensive technical SEO audit covering crawlability, indexation, site speed, and structured data validation.",
  "thumbnailUrl": "https://example.com/images/tech-seo-audit-thumb.jpg",
  "uploadDate": "2025-07-15T10:00:00+00:00",
  "duration": "PT22M45S",
  "contentUrl": "https://example.com/videos/tech-seo-audit.mp4",
  "embedUrl": "https://www.youtube.com/embed/dQw4w9WgXcQ",
  "interactionStatistic": {
    "@type": "InteractionCounter",
    "interactionType": { "@type": "WatchAction" },
    "userInteractionCount": 48200
  },
  "regionsAllowed": "US,CA,GB,AU"
}
```

---

## 12. Course

```json
{
  "@context": "https://schema.org",
  "@type": "Course",
  "name": "Advanced SEO Certification",
  "description": "Master technical SEO, content strategy, link building, and analytics in this 12-week professional certification program.",
  "provider": {
    "@type": "Organization",
    "name": "Digital Marketing Institute",
    "url": "https://www.dmi-example.com",
    "sameAs": "https://www.linkedin.com/school/dmi-example"
  },
  "offers": {
    "@type": "Offer",
    "price": "799.00",
    "priceCurrency": "USD",
    "availability": "https://schema.org/InStock",
    "url": "https://www.dmi-example.com/courses/advanced-seo",
    "category": "Paid"
  },
  "hasCourseInstance": {
    "@type": "CourseInstance",
    "courseMode": "online",
    "courseSchedule": {
      "@type": "Schedule",
      "duration": "PT12W",
      "repeatFrequency": "Weekly",
      "repeatCount": 12
    }
  },
  "courseCode": "SEO-ADV-101",
  "educationalLevel": "Advanced",
  "inLanguage": "en",
  "aggregateRating": {
    "@type": "AggregateRating",
    "ratingValue": "4.8",
    "ratingCount": "956"
  }
}
```

---

## 13. SoftwareApplication

```json
{
  "@context": "https://schema.org",
  "@type": "SoftwareApplication",
  "name": "SEO Analyzer Pro",
  "operatingSystem": "Web, Windows, macOS",
  "applicationCategory": "BusinessApplication",
  "description": "All-in-one SEO analysis tool for keyword research, site audits, rank tracking, and backlink analysis.",
  "offers": {
    "@type": "Offer",
    "price": "49.00",
    "priceCurrency": "USD"
  },
  "aggregateRating": {
    "@type": "AggregateRating",
    "ratingValue": "4.5",
    "ratingCount": "2130"
  },
  "screenshot": "https://example.com/images/seo-analyzer-dashboard.png",
  "softwareVersion": "3.2.1",
  "downloadUrl": "https://example.com/download",
  "featureList": "Keyword Research, Site Audit, Rank Tracking, Backlink Analysis, Competitor Analysis"
}
```

---

## 14. JobPosting

```json
{
  "@context": "https://schema.org",
  "@type": "JobPosting",
  "title": "Senior SEO Specialist",
  "description": "<p>We are looking for a Senior SEO Specialist to lead our organic search strategy. You will manage technical SEO, content optimization, and link building campaigns across our portfolio of websites.</p><h3>Requirements</h3><ul><li>5+ years of SEO experience</li><li>Proficiency with Ahrefs, Screaming Frog, and Google Search Console</li><li>Strong analytical and communication skills</li></ul>",
  "datePosted": "2025-08-01",
  "validThrough": "2025-10-01T00:00:00+00:00",
  "employmentType": "FULL_TIME",
  "hiringOrganization": {
    "@type": "Organization",
    "name": "Acme Digital Solutions",
    "sameAs": "https://example.com",
    "logo": "https://example.com/logo.png"
  },
  "jobLocation": {
    "@type": "Place",
    "address": {
      "@type": "PostalAddress",
      "streetAddress": "456 Tech Drive",
      "addressLocality": "Austin",
      "addressRegion": "TX",
      "postalCode": "78701",
      "addressCountry": "US"
    }
  },
  "jobLocationType": "TELECOMMUTE",
  "applicantLocationRequirements": {
    "@type": "Country",
    "name": "US"
  },
  "baseSalary": {
    "@type": "MonetaryAmount",
    "currency": "USD",
    "value": {
      "@type": "QuantitativeValue",
      "minValue": 90000,
      "maxValue": 130000,
      "unitText": "YEAR"
    }
  },
  "directApply": true
}
```

---

## 15. Person

```json
{
  "@context": "https://schema.org",
  "@type": "Person",
  "@id": "https://example.com/authors/sarah-johnson/#person",
  "name": "Sarah Johnson",
  "url": "https://example.com/authors/sarah-johnson",
  "image": "https://example.com/images/sarah-johnson.jpg",
  "jobTitle": "Head of SEO",
  "worksFor": {
    "@type": "Organization",
    "name": "Acme Digital Solutions",
    "@id": "https://example.com/#organization"
  },
  "description": "Sarah Johnson is an SEO strategist with 12 years of experience in technical SEO and content optimization.",
  "sameAs": [
    "https://twitter.com/sarahjseo",
    "https://www.linkedin.com/in/sarahjohnson-seo",
    "https://github.com/sarahj-seo"
  ],
  "knowsAbout": ["SEO", "Technical SEO", "Content Strategy", "Structured Data"],
  "alumniOf": {
    "@type": "CollegeOrUniversity",
    "name": "University of Texas at Austin"
  }
}
```

---

## Multi-Entity @graph Template

Combine multiple types on a single page (e.g., homepage with Organization + WebSite + BreadcrumbList):

```json
{
  "@context": "https://schema.org",
  "@graph": [
    {
      "@type": "Organization",
      "@id": "https://example.com/#organization",
      "name": "Acme Digital Solutions",
      "url": "https://example.com",
      "logo": {
        "@type": "ImageObject",
        "url": "https://example.com/logo.png"
      },
      "sameAs": [
        "https://twitter.com/acmedigital",
        "https://www.linkedin.com/company/acmedigital"
      ]
    },
    {
      "@type": "WebSite",
      "@id": "https://example.com/#website",
      "url": "https://example.com/",
      "name": "Acme Digital Solutions",
      "publisher": { "@id": "https://example.com/#organization" },
      "potentialAction": {
        "@type": "SearchAction",
        "target": {
          "@type": "EntryPoint",
          "urlTemplate": "https://example.com/search?q={search_term_string}"
        },
        "query-input": "required name=search_term_string"
      }
    },
    {
      "@type": "WebPage",
      "@id": "https://example.com/#webpage",
      "url": "https://example.com/",
      "name": "Acme Digital Solutions - SEO Tools and Resources",
      "isPartOf": { "@id": "https://example.com/#website" },
      "about": { "@id": "https://example.com/#organization" },
      "description": "SEO tools, guides, and digital marketing resources from Acme Digital Solutions."
    }
  ]
}
```

---

## Usage Notes

1. **Replace all example data** with real values from your page content.
2. **Remove properties you do not have data for** -- do not leave empty strings or placeholder values.
3. **Use HTTPS URLs** for all `url`, `image`, `logo`, and `item` properties.
4. **Dates must be ISO 8601** format: `YYYY-MM-DD` or `YYYY-MM-DDTHH:MM:SS+00:00`.
5. **Validate** every template after customization using the [Rich Results Test](https://search.google.com/test/rich-results).
6. **One script tag per page** is preferred when using `@graph`; multiple script tags are also valid.

**MCP Tool:** Use `generate_schema` to automatically produce JSON-LD from page content, then compare against these templates for completeness.
