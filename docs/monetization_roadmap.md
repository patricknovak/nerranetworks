# Monetization Roadmap

This document outlines the monetization strategy for the Tesla Shorts Time
podcast network.

## Current State (Feb 2026)

| Show | Episodes | Frequency | Estimated Monthly Downloads |
|------|----------|-----------|---------------------------|
| Tesla Shorts Time | ~60+ | Daily | TBD (enable OP3 to measure) |
| Omni View | ~50+ | Daily | TBD |
| Fascinating Frontiers | ~30+ | Every other day | TBD |
| Planetterrian Daily | ~30+ | Every other day | TBD |
| Environmental Intelligence | New | Weekdays | TBD |

**First step: Enable OP3 analytics to get accurate download numbers.**

## Revenue Streams

### 1. Programmatic Ads (CPM-based)

**How it works:** Ad networks dynamically insert pre-roll, mid-roll, or
post-roll ads into episodes based on listener demographics and content.

| Network | Min Downloads/Month | CPM Range | Notes |
|---------|-------------------|-----------|-------|
| Spotify Ad Network | 100+ | $15-25 | Spotify-only listeners |
| Podcorn | None | $15-50 | Marketplace model, host-read preferred |
| AdvertiseCast | 1,000+ | $18-25 | Traditional programmatic |
| Megaphone | 5,000+ | $20-30 | Enterprise-grade, Spotify-owned |
| Acast | 1,000+ | $15-25 | Good for growing shows |
| Anchor/Spotify | None | $10-18 | Easy to start, lower CPM |

**Target:** 5,000+ downloads/month per show to unlock premium ad networks.

**Estimated revenue at scale:**
- 5,000 downloads × $20 CPM = $100/month per show
- 10,000 downloads × $25 CPM = $250/month per show
- With 5 shows at 10K: ~$1,250/month total

### 2. Newsletter Sponsorships

With Buttondown newsletters for Omni View and Environmental Intelligence:

| Subscriber Count | Sponsorship Rate (per issue) | Monthly Revenue |
|-----------------|------------------------------|-----------------|
| 500 | $25-50 | $100-200 |
| 1,000 | $50-100 | $200-400 |
| 5,000 | $200-500 | $800-2,000 |

**Environmental Intelligence** has strong monetization potential due to
its niche professional audience (environmental consultants, regulators).
Niche B2B newsletters command higher CPMs than general interest.

### 3. Premium Content / Membership

**Potential tiers:**

| Tier | Price | Benefits |
|------|-------|----------|
| Free | $0 | Daily podcast + written summary |
| Supporter | $5/month | Ad-free episodes, early access |
| Professional | $15/month | Weekly deep-dive report (env_intel), data exports |

**Platforms:** Patreon, Buy Me a Coffee, Memberful, or Buttondown paid tier.

### 4. Affiliate Links

Relevant affiliate programs by show:

| Show | Potential Affiliates |
|------|---------------------|
| Tesla Shorts Time | Stock trading platforms, EV accessories, financial tools |
| Omni View | News subscriptions, VPN services, educational platforms |
| Fascinating Frontiers | Telescopes, science gear, online courses, books |
| Planetterrian Daily | Health supplements, lab testing, longevity products |
| Environmental Intelligence | Environmental software, lab services, training courses |

Typical affiliate commission: 5-30% per conversion.

## Milestone Timeline

### Phase 1: Measurement (Now)
- [x] Enable OP3 analytics prefix in RSS feeds
- [ ] Set up OP3 dashboard and verify download tracking
- [ ] Baseline download numbers for each show (2 weeks of data)

### Phase 2: Directory Distribution (Month 1)
- [ ] Submit all shows to Apple Podcasts, Spotify, Amazon Music
- [ ] Submit to Podcast Index, Pocket Casts, iHeartRadio
- [ ] See `docs/podcast_directories.md` for full checklist

### Phase 3: Newsletter Growth (Months 1-3)
- [ ] Launch Omni View newsletter
- [ ] Launch Environmental Intelligence newsletter
- [ ] Cross-promote between podcast and newsletter
- [ ] Target: 250 subscribers per newsletter by month 3

### Phase 4: First Revenue (Months 3-6)
- [ ] Apply to Podcorn or Anchor/Spotify for programmatic ads
- [ ] Add affiliate links to show notes
- [ ] Evaluate newsletter sponsorship opportunities for env_intel
- [ ] Target: $100-300/month combined

### Phase 5: Scale (Months 6-12)
- [ ] Apply to premium ad networks (Megaphone, AdvertiseCast)
- [ ] Launch membership/supporter tier
- [ ] Explore Environmental Intelligence premium tier
- [ ] Target: $500-1,500/month combined

## Cost Structure

| Item | Monthly Cost | Notes |
|------|-------------|-------|
| ElevenLabs TTS | ~$22 | Creator plan, ~70K chars/day |
| xAI/Grok API | ~$5-15 | Usage-based |
| GitHub Actions | Free | Open source repo |
| Cloudflare R2 | ~$0-5 | Free tier covers most usage |
| Buttondown | Free | Free tier up to 100 subscribers |
| Domain (optional) | ~$1 | If custom domain added |
| **Total** | **~$28-43/month** | |

**Break-even target:** ~2,000-3,000 total monthly downloads across all shows
with entry-level programmatic ads.

## Key Metrics to Track

1. **Downloads per episode** — via OP3
2. **Unique listeners per month** — via OP3
3. **Newsletter subscribers** — via Buttondown
4. **Newsletter open rate** — target >40%
5. **Directory rankings** — Apple Podcasts category placement
6. **Revenue per show** — once monetization begins
