# seo-schema-structured-data

Expert guide for Schema.org structured data and JSON-LD implementation.

## Purpose
Teaches Claude how to create, validate, and troubleshoot Schema.org structured data using JSON-LD format. Covers all Google-supported schema types, required and recommended properties, rich result eligibility, multi-entity page patterns, dynamic schema generation, and compliance with Google's structured data policies.

## Activation Triggers
This skill activates when the user mentions: structured data, JSON-LD, schema markup, Schema.org, rich results, rich snippets, FAQ schema, Product schema, Article schema, HowTo schema, LocalBusiness schema, Organization schema, BreadcrumbList, sitelinks search box, Event schema, Recipe schema, VideoObject, Course schema, SoftwareApplication schema, JobPosting schema, @graph pattern, schema validation, Rich Results Test.

## Files
| File | Lines | Description |
|------|-------|-------------|
| SKILL.md | ~300 | Core JSON-LD fundamentals, all Google-supported types with required/recommended properties, dynamic generation patterns, validation workflow, and common pitfalls |
| SCHEMA_TEMPLATES.md | ~300 | Ready-to-use, syntactically valid JSON-LD templates for 15 schema types plus a multi-entity @graph example |
| VALIDATION_RULES.md | ~200 | Google's required/recommended properties per type, value constraints (dates, URLs, enums), content-visibility rules, spam policies, common errors with fixes, and testing workflow |
| RICH_RESULTS_GUIDE.md | ~150 | Schema type to rich result mapping table, descriptions of each rich result appearance, eligibility requirements, Search Console monitoring, common failure reasons, and page-category recommendations |

## MCP Tools Used
- `extract_schema` -- extract existing JSON-LD, Microdata, and RDFa structured data from any URL
- `generate_schema` -- generate valid JSON-LD markup for a specified schema type based on page content

## Evaluation Scenarios
1. User asks to add FAQ schema to a page with visible Q&A content
2. User needs Product schema with pricing, availability, and reviews for an e-commerce page
3. User wants to implement a multi-entity @graph with Organization + WebSite + BreadcrumbList on a homepage
4. User has structured data errors in Search Console and needs to diagnose and fix them
5. User wants to know which schema types to implement for a recipe blog
6. User asks why their rich results are not appearing despite having schema markup
7. User needs to generate Article schema for a news site with multiple authors
8. User wants to add Event schema for a hybrid (in-person + virtual) conference
9. User needs to validate that existing schema complies with Google's spam policies
10. User asks for a complete LocalBusiness schema for a restaurant with opening hours and menu link
