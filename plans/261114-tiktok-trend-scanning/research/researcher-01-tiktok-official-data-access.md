# TikTok Official / ToS-Compliant Data Access for Trend Scanning (as of 2026-11-14)

Scope: keyword/hashtag/creator trend discovery + metrics (views, likes, comments, shares, date, author, duration) for a small Vietnam-based commercial brand. Constraint: official or terms-compliant only.

Confidence legend: [V] verified in search result; [U] unverified / from secondary source or memory, check official docs before relying on it.

## Bottom line
No official TikTok API gives commercial keyword/hashtag trend discovery with view counts. The only official paths are either research-only (excluded for commercial use) or user-OAuth (own/authorized accounts only). Official-compliant scanning at scale is not available to this business. Realistic options: (a) manual/Creative Center viewing plus internal notes, (b) paid third-party providers with explicit ToS risk, (c) redesign the feature around accounts the brand is authorized to read.

## 1. TikTok Research API (now "Research Tools")
- Eligibility: approved academic / non-profit researchers in eligible regions (US, EU/EEA, UK). Commercial users excluded. [V] per multiple secondary sources (toolzerhub, apidojo, imisofts, tokconnect)
- Research Terms reportedly effective 2026-01-22 bar commercial use beyond publishing research papers. [V secondary, toolzerhub]
- Review ~4 weeks. Quota ~1,000 requests/day. [V secondary]
- Fields: video query by keyword/hashtag/username, metrics (views, likes, comments, shares), date, author, duration, region. [U] field list from memory.
- Cost: free but unattainable for this business.
- Vietnam brand: NO. Not an eligible applicant type.
- Sources: https://toolzerhub.com/blog/tiktok-research-api-access ; https://apidojo.io/blog/tiktok-api/research-api/ ; https://tokconnect.com/guides/tiktok-research-api/ ; https://imisofts.com/blog/tiktok-api-pricing/

## 2. Commercial Content API / Commercial Content Library (Ad Library)
- Public ad archive: library.tiktok.com. Covers ads in EEA, UK, Switzerland (some sources add Turkey). [V secondary]
- Commercial Content API (programmatic): sources conflict. One says open to public/researchers by application, free, EU data only. Others say restricted to approved academic/non-profit researchers in US/EU, non-commercial, approval takes weeks-months, marketers cannot apply. [V conflicting]
- Scope: ADS ONLY. Not organic trending videos. Useless for organic trend discovery.
- Cost: free. Vietnam: no VN ad coverage in EU-only archive. Not useful.
- Sources: https://adlibrary.com/guides/tiktok-ad-library-api ; https://socialfuel.io/blog/tiktok-ad-library-a-2026-guide-for-marketers

## 3. TikTok Creative Center (Top Ads, trending hashtags, songs, videos)
- Public web dashboard (ads.tiktok.com / creator.tiktok.com Creative Center). Trending hashtags, songs, videos, creators by country incl. Vietnam [U].
- Official API or export: none found. [U] no documented public API; no CSV export known.
- ToS: TikTok ToS and Creative Center terms prohibit automated scraping / unauthorized access. Scraping it = ToS breach. Not verified in this search (search returned nothing on Creative Center terms). [U — must check actual Creative Center terms page before any automation]
- Practical use: manual review by staff, copy insights into internal notes. Compliant.
- Cost: free. Vietnam: country filter likely includes VN [U].

## 4. Display API / Login Kit (user OAuth)
- Requires end-user authorization (OAuth). Scopes: user.info.basic, video.list, video.query, user.info.stats. [V developers.tiktok.com]
- video.list (POST /v2/video/list/): public posts of the AUTHORIZING user only, sorted by create_time desc, page size default 10, max 20. [V]
- video.query: up to 20 video IDs per request, own videos only (per authorized user). [V]
- Rate limit reportedly 600 req/min per endpoint, sliding window (blog source, verify). [V secondary]
- Fields: id, title, cover, duration, create_time, view/like/comment/share counts (stats scope), etc. [U partial]
- Scope check: user may grant some scopes and decline others; check token response. [V]
- Usefulness: only the brand's own account (or accounts that actively log in and consent). Cannot discover trends or read third-party creators. Not a trend tool.
- Vietnam brand: yes can register a developer app (Vietnam not blocked per se) [U]; usefulness limited to own account analytics.
- Sources: https://developers.tiktok.com/docs/en/display-api-get-started ; https://developers.tiktok.com/docs/en/tiktok-api-v2-video-list ; https://developers.tiktok.com/docs/en/tiktok-api-v2-video-query ; https://www.getphyllo.com/post/tiktok-api-scopes

## 5. TikTok API for Business / Marketing API
- Marketing API: ad campaign management, reporting for own ads. [U]
- Trend / hashtag-insight endpoints: none known in official Business API. [U — not verified; check Business API endpoint catalog]
- TikTok Shop / Affiliate / Creator Marketplace APIs: partner-gated, for sellers/brands with agreements. Possibly relevant if brand sells on TikTok Shop, but not for keyword trend scanning. [U]
- Vietnam: Business accounts exist in VN; API partner approval required. [U]
- Verdict: not a trend-discovery source.

## 6. oEmbed endpoint
- Endpoint: https://www.tiktok.com/oembed?url=<video_url>. No auth. [U from memory — search did not verify]
- Returns: title/caption, author_name, author_url, thumbnail_url, embed HTML, embed_product_id, version, type. No view/like/comment/share counts, no publish date reliably. [U]
- Rate limits: undocumented; use sparingly. [U]
- Use: enrich a known URL with title/author/thumb for display; not discovery, not metrics.
- Compliant: public, documented for embedding. Still store only what ToS allows.

## 7. Paid third-party providers
Pricing order of magnitude (from secondary sources, approximate):
- Apify TikTok actors: pay-per-result / compute units, roughly USD 0.5-5 per 1k results. [U]
- TikAPI, EnsembleData, RapidAPI TikTok APIs: subscription tiers, ~USD 50-500/month for moderate volume; per-call ~USD 0.001-0.002 (xpoz cites up to ~USD 1.88/1k calls). [V secondary: https://www.xpoz.ai/blog/guides/tiktok-api-pricing-2026/ ]
- Bright Data / ScrapeBadger-style: enterprise, higher cost. [U]
- Reliability: scrapers break on TikTok anti-bot changes; data gaps (DataShake notes coverage limits). [V secondary: https://www.datashake.com/blog/tiktok-data-coverage-in-2026-what-social-intelligence-teams-need-to-know ]
- Legal / ToS: these providers scrape public pages. TikTok ToS prohibits unauthorized scraping. Legal exposure for the brand is real even if providers claim "public data". Using them is NOT terms-compliant under the owner's strict standard. Stated honestly: ToS-breaching in TikTok's terms; enforcement risk low-moderate for small firms, but it fails the owner's requirement.
- Vietnam: payment by card/USD may be a practical barrier [U].
- Sources: https://scrapebadger.com/blog/tiktok-scraping-apis-in-2026-the-complete-deep-guide ; https://sociavault.com/blog/tiktok-api-free-2026

## Ranked recommendation (for owner's constraints)
1. Creative Center manual review + internal notes (free, compliant, low automation). Confirm its ToS first. Covers trending hashtags/videos for VN.
2. Display API via OAuth on the brand's OWN TikTok account to pull own-video metrics (compliant, free, useful for benchmarking own performance, not trends).
3. Own YouTube pipeline already exists; keep it as the primary automated trend source. Add TikTok manually or via Creative Center only.
4. Paid third-party scrapers: only if owner accepts ToS risk. Owner prefers no, so exclude by default.
5. oEmbed: use only to enrich URLs already collected manually (title, author, thumbnail). Compliant.

## NOT realistically available to this business
- Research API / Research Tools (academic/non-profit only, commercial excluded).
- Commercial Content API (researcher-gated; EU-only data; ads only).
- Any official endpoint returning keyword/hashtag organic trending videos with view counts for third parties (none exists for commercial users).
- Display API for discovering or reading third-party creators (user-consent per account only).
- Marketing/Business API trend endpoints (none found).
- Automated Creative Center scraping (ToS-prohibited).

## Implications for the app (YAGNI/KISS)
- Do not build a TikTok connector for keyword discovery. Build a manual import (paste URL -> oEmbed enrichment) or a CSV import from Creative Center review.
- If own-account analytics is wanted later, add a Display API OAuth connector (small scope).
- Keep downloads with yt-dlp only if the owner accepts it for TikTok; treat as same ToS issue as scraping. Recommend excluding.

## Unresolved questions
1. Exact current Creative Center terms on automated access and any export feature (not verified; must read the official page).
2. Whether the Commercial Content API accepts commercial applicants in late 2026 (sources conflict).
3. Whether Business API / TikTok Shop APIs expose any hashtag or trend-insight endpoint for brand partners.
4. Current Display API rate limit (blog says 600 req/min; verify in official docs).
5. oEmbed field set and limits (from memory; verify live).
6. Whether TikTok's Research Terms (2026-01-22) changed commercial exclusions further.
7. Vietnam-specific: any local TikTok developer or regulatory constraint (Decree on personal data, cross-border data) affecting storage of creator data.
8. Actual Apify/TikAPI pricing as of late 2026 (secondary sources only).

## Sources
- https://toolzerhub.com/blog/tiktok-research-api-access
- https://apidojo.io/blog/tiktok-api/research-api/
- https://tokconnect.com/guides/tiktok-research-api/
- https://imisofts.com/blog/tiktok-api-pricing/
- https://adlibrary.com/guides/tiktok-ad-library-api
- https://socialfuel.io/blog/tiktok-ad-library-a-2026-guide-for-marketers
- https://developers.tiktok.com/docs/en/display-api-get-started
- https://developers.tiktok.com/docs/en/tiktok-api-v2-video-list
- https://developers.tiktok.com/docs/en/tiktok-api-v2-video-query
- https://www.getphyllo.com/post/tiktok-api-scopes
- https://www.getphyllo.com/post/tiktok-api-rate-limits-in-2026-quotas-errors-workarounds
- https://www.xpoz.ai/blog/guides/tiktok-api-pricing-2026/
- https://www.datashake.com/blog/tiktok-data-coverage-in-2026-what-social-intelligence-teams-need-to-know
- https://scrapebadger.com/blog/tiktok-scraping-apis-in-2026-the-complete-deep-guide
- https://sociavault.com/blog/tiktok-api-free-2026
- Official pages not fetched: https://developers.tiktok.com/ (Research Tools, Commercial Content API, oEmbed), https://www.tiktok.com/legal/ (Terms), Creative Center terms.
