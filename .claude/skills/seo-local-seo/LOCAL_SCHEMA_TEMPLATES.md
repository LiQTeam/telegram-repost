# Local SEO Schema Templates

JSON-LD templates for local business structured data.

---

## LocalBusiness (Generic)

```json
{
  "@context": "https://schema.org",
  "@type": "LocalBusiness",
  "name": "Business Name",
  "description": "Brief description of the business and services.",
  "url": "https://www.example.com",
  "telephone": "+1-512-555-0123",
  "email": "info@example.com",
  "address": {
    "@type": "PostalAddress",
    "streetAddress": "123 Main Street, Suite 100",
    "addressLocality": "Austin",
    "addressRegion": "TX",
    "postalCode": "78701",
    "addressCountry": "US"
  },
  "geo": {
    "@type": "GeoCoordinates",
    "latitude": 30.2672,
    "longitude": -97.7431
  },
  "openingHoursSpecification": [
    {
      "@type": "OpeningHoursSpecification",
      "dayOfWeek": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
      "opens": "08:00",
      "closes": "17:00"
    },
    {
      "@type": "OpeningHoursSpecification",
      "dayOfWeek": "Saturday",
      "opens": "09:00",
      "closes": "14:00"
    }
  ],
  "image": "https://www.example.com/images/storefront.jpg",
  "priceRange": "$$",
  "aggregateRating": {
    "@type": "AggregateRating",
    "ratingValue": "4.8",
    "reviewCount": "127"
  },
  "sameAs": [
    "https://www.facebook.com/businessname",
    "https://www.instagram.com/businessname",
    "https://www.yelp.com/biz/businessname"
  ]
}
```

---

## Restaurant

```json
{
  "@context": "https://schema.org",
  "@type": "Restaurant",
  "name": "La Bella Italian Kitchen",
  "description": "Authentic Italian restaurant in downtown Austin serving handmade pasta and wood-fired pizza since 2010.",
  "url": "https://www.labellaaustin.com",
  "telephone": "+1-512-555-0456",
  "address": {
    "@type": "PostalAddress",
    "streetAddress": "456 Congress Avenue",
    "addressLocality": "Austin",
    "addressRegion": "TX",
    "postalCode": "78701",
    "addressCountry": "US"
  },
  "geo": {
    "@type": "GeoCoordinates",
    "latitude": 30.2669,
    "longitude": -97.7428
  },
  "servesCuisine": "Italian",
  "menu": "https://www.labellaaustin.com/menu",
  "acceptsReservations": "True",
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
      "opens": "11:00",
      "closes": "21:00"
    }
  ],
  "priceRange": "$$$",
  "aggregateRating": {
    "@type": "AggregateRating",
    "ratingValue": "4.6",
    "reviewCount": "342"
  },
  "image": [
    "https://www.labellaaustin.com/images/restaurant-exterior.jpg",
    "https://www.labellaaustin.com/images/pasta-dish.jpg"
  ]
}
```

---

## MedicalBusiness (Doctor/Clinic)

```json
{
  "@context": "https://schema.org",
  "@type": "MedicalBusiness",
  "name": "Austin Family Medical Center",
  "description": "Family medicine clinic in Austin, TX providing primary care, urgent care, and preventive health services.",
  "url": "https://www.austinfamilymedical.com",
  "telephone": "+1-512-555-0789",
  "address": {
    "@type": "PostalAddress",
    "streetAddress": "789 Healthcare Blvd",
    "addressLocality": "Austin",
    "addressRegion": "TX",
    "postalCode": "78731",
    "addressCountry": "US"
  },
  "geo": {
    "@type": "GeoCoordinates",
    "latitude": 30.3456,
    "longitude": -97.7612
  },
  "medicalSpecialty": "Family Medicine",
  "openingHoursSpecification": [
    {
      "@type": "OpeningHoursSpecification",
      "dayOfWeek": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
      "opens": "07:30",
      "closes": "17:30"
    }
  ],
  "availableService": [
    {
      "@type": "MedicalProcedure",
      "name": "Annual Physical Exam"
    },
    {
      "@type": "MedicalProcedure",
      "name": "Urgent Care"
    }
  ],
  "aggregateRating": {
    "@type": "AggregateRating",
    "ratingValue": "4.9",
    "reviewCount": "215"
  }
}
```

---

## LegalService (Attorney/Law Firm)

```json
{
  "@context": "https://schema.org",
  "@type": "LegalService",
  "name": "Smith & Associates Personal Injury Law",
  "description": "Austin personal injury law firm specializing in car accidents, workplace injuries, and medical malpractice cases.",
  "url": "https://www.smithlawaustin.com",
  "telephone": "+1-512-555-0321",
  "address": {
    "@type": "PostalAddress",
    "streetAddress": "321 Legal Center Dr, Suite 500",
    "addressLocality": "Austin",
    "addressRegion": "TX",
    "postalCode": "78701",
    "addressCountry": "US"
  },
  "geo": {
    "@type": "GeoCoordinates",
    "latitude": 30.2700,
    "longitude": -97.7400
  },
  "areaServed": {
    "@type": "State",
    "name": "Texas"
  },
  "openingHoursSpecification": [
    {
      "@type": "OpeningHoursSpecification",
      "dayOfWeek": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
      "opens": "08:00",
      "closes": "18:00"
    }
  ],
  "priceRange": "Free Consultation",
  "aggregateRating": {
    "@type": "AggregateRating",
    "ratingValue": "4.7",
    "reviewCount": "89"
  }
}
```

---

## HomeAndConstructionBusiness (Plumber/Electrician/HVAC)

```json
{
  "@context": "https://schema.org",
  "@type": "Plumber",
  "name": "Austin Plumbing Co",
  "description": "Licensed plumber in Austin, TX providing emergency plumbing, drain cleaning, and water heater installation. Available 24/7.",
  "url": "https://www.austinplumbingco.com",
  "telephone": "+1-512-555-0147",
  "address": {
    "@type": "PostalAddress",
    "streetAddress": "147 Trades Way",
    "addressLocality": "Austin",
    "addressRegion": "TX",
    "postalCode": "78745",
    "addressCountry": "US"
  },
  "geo": {
    "@type": "GeoCoordinates",
    "latitude": 30.2100,
    "longitude": -97.7700
  },
  "areaServed": [
    {
      "@type": "City",
      "name": "Austin"
    },
    {
      "@type": "City",
      "name": "Round Rock"
    },
    {
      "@type": "City",
      "name": "Cedar Park"
    }
  ],
  "openingHoursSpecification": [
    {
      "@type": "OpeningHoursSpecification",
      "dayOfWeek": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
      "opens": "00:00",
      "closes": "23:59"
    }
  ],
  "priceRange": "$$",
  "hasOfferCatalog": {
    "@type": "OfferCatalog",
    "name": "Plumbing Services",
    "itemListElement": [
      {
        "@type": "OfferCatalog",
        "name": "Emergency Plumbing",
        "itemListElement": [
          {
            "@type": "Offer",
            "itemOffered": {
              "@type": "Service",
              "name": "Burst Pipe Repair"
            }
          },
          {
            "@type": "Offer",
            "itemOffered": {
              "@type": "Service",
              "name": "Sewer Backup Repair"
            }
          }
        ]
      }
    ]
  },
  "aggregateRating": {
    "@type": "AggregateRating",
    "ratingValue": "4.8",
    "reviewCount": "203"
  }
}
```

---

## Multi-Location (Using @graph)

For businesses with multiple locations on a single website:

```json
{
  "@context": "https://schema.org",
  "@graph": [
    {
      "@type": "Organization",
      "@id": "https://www.example.com/#organization",
      "name": "Business Name",
      "url": "https://www.example.com",
      "logo": "https://www.example.com/logo.png"
    },
    {
      "@type": "LocalBusiness",
      "@id": "https://www.example.com/locations/austin/#location",
      "name": "Business Name - Austin",
      "parentOrganization": { "@id": "https://www.example.com/#organization" },
      "address": {
        "@type": "PostalAddress",
        "streetAddress": "123 Main St",
        "addressLocality": "Austin",
        "addressRegion": "TX",
        "postalCode": "78701"
      },
      "telephone": "+1-512-555-0001"
    },
    {
      "@type": "LocalBusiness",
      "@id": "https://www.example.com/locations/dallas/#location",
      "name": "Business Name - Dallas",
      "parentOrganization": { "@id": "https://www.example.com/#organization" },
      "address": {
        "@type": "PostalAddress",
        "streetAddress": "456 Commerce St",
        "addressLocality": "Dallas",
        "addressRegion": "TX",
        "postalCode": "75201"
      },
      "telephone": "+1-214-555-0002"
    }
  ]
}
```

---

## Usage Notes

- Place JSON-LD in `<script type="application/ld+json">` in the `<head>` section
- Use one schema per location page (don't put all locations on one page)
- Ensure all data matches the visible page content
- Keep `geo` coordinates accurate (use Google Maps to find exact lat/long)
- `sameAs` should list all official social media profiles
- `aggregateRating` must reflect real reviews visible on your site or a linked platform

**MCP Tool:** Use `generate_schema` with `type: "LocalBusiness"` to generate customized schema for any local business type.
