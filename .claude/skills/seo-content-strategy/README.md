# seo-content-strategy

Expert guide for content-driven SEO strategy.

## Purpose

Teaches Claude how to conduct keyword research, plan content clusters, analyze search intent, build topic authority through E-E-A-T signals, create content briefs, perform content gap analysis, and plan content calendars for SEO. This skill provides the strategic layer that connects keyword data to content creation and organic growth.

## Activation Triggers

This skill activates when the user mentions: keyword research, content strategy, content clusters, topic clusters, pillar pages, search intent, E-E-A-T, content briefs, content calendar, content gap analysis, content planning, topic authority, YMYL, keyword difficulty, search volume, long-tail keywords, content silos, content freshness, content updates.

## Files

| File | Lines | Description |
|------|-------|-------------|
| SKILL.md | ~300 | Core content strategy guide: keyword research, search intent, content clusters, E-E-A-T, content briefs, gap analysis, freshness strategy |
| KEYWORD_RESEARCH_GUIDE.md | ~200 | Complete keyword research process: seed generation, long-tail expansion, question mining, filtering, scoring, prioritization matrix |
| CONTENT_CLUSTER_TEMPLATES.md | ~250 | 5 ready-to-use content cluster templates: SaaS, E-commerce, Local Business, B2B Service, Publisher/Media — each with pillar structure, cluster topics, and linking plans |
| SEARCH_INTENT_PATTERNS.md | ~200 | Search intent classification reference: 4 intent types, 50+ classified example queries, SERP feature expectations, content format recommendations, mismatch detection |

## MCP Tools Used

- `research_keywords` — keyword discovery, search volume and difficulty data, long-tail expansion, trend data
- `analyze_serp` — SERP feature detection, search intent verification, competitor identification, ranking content type analysis
- `analyze_page` — content analysis on competitor pages, heading extraction, word count, on-page audit for content brief creation

## Evaluation Scenarios

1. **Keyword research request:** User asks to find keywords for a new blog. Claude should follow the 8-step process in KEYWORD_RESEARCH_GUIDE.md, use `research_keywords` for data, and deliver a prioritized keyword list grouped by intent.

2. **Content cluster planning:** User wants to build topical authority around a subject. Claude should select the appropriate template from CONTENT_CLUSTER_TEMPLATES.md, customize it with specific keywords, and produce a pillar page outline plus 8-12 cluster topics with a linking plan.

3. **Search intent analysis:** User provides a list of keywords and asks what content to create. Claude should classify each keyword by intent using SEARCH_INTENT_PATTERNS.md, recommend content formats, and flag any potential intent mismatches.

4. **Content brief creation:** User needs a content brief for a specific keyword. Claude should use `analyze_serp` and `analyze_page` on top-ranking competitors, then produce a complete brief following the template in SKILL.md.

5. **Content gap analysis:** User wants to find content opportunities vs. competitors. Claude should analyze competitor pages with `analyze_page`, identify topic/depth/freshness/format gaps, and prioritize them using the impact matrix from KEYWORD_RESEARCH_GUIDE.md.

6. **E-E-A-T evaluation:** User asks how to improve content quality signals. Claude should audit current E-E-A-T signals against the framework in SKILL.md and provide specific, actionable recommendations for Experience, Expertise, Authoritativeness, and Trustworthiness.

7. **Content refresh decision:** User has aging content with declining traffic. Claude should apply the update-vs-create-new framework from SKILL.md, re-analyze current SERP intent, and recommend whether to update, rewrite, or create new content.
