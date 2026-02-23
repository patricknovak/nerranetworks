# Podcast Network Quality Audit & Comprehensive Fix Plan

**Date:** February 23, 2026
**Scope:** All 5 shows — Tesla Shorts Time (TST), Omni View (OV), Fascinating Frontiers (FF), Planetterrian Daily (PT), Environmental Intelligence (EI)
**Method:** Reviewed last 5 episodes per show + full code-level audit of all scripts and engine modules

---

## Part 1: Issues Found Per Show

### TESLA SHORTS TIME — 12 Issues (5 CRITICAL, 4 HIGH, 3 MEDIUM)

| # | Severity | Issue | Frequency |
|---|----------|-------|-----------|
| T1 | CRITICAL | **X Takeover is 100% duplicate of Top 10** — all 5 items repeat Top 10 stories verbatim with different framing. Listener hears every story twice. | 5/5 episodes |
| T2 | CRITICAL | **Stock price mentioned** in intro + closing despite prompt explicitly forbidding it. Lines 2109 & 2115 say "Do NOT mention TSLA stock price" but digest input starts with `**TSLA:** $price` | 5/5 episodes |
| T3 | CRITICAL | **Host self-identifies as "Patrick in Vancouver"** — violates "no personal names" rule (line 2101). Code strips "Patrick:" prefix (line 2495) but NOT mid-sentence "I'm Patrick" | 5/5 episodes |
| T4 | HIGH | **Top 10 never has 10 items** — counts range 6-9. On low-article days, prompt forces "Top 10" label but Grok can't fill it | 5/5 episodes |
| T5 | HIGH | **Short Spot always reuses a Top 10 article** — same URL, same story. No enforcement that Short Spot must be unique | 5/5 episodes |
| T6 | HIGH | **FSD subscription story ran 3 consecutive days** (Feb 13-15). Cross-day dedup (72% threshold) missed it because headlines differed enough | 3/5 episodes |
| T7 | HIGH | **Semi production story recycled** (Feb 11 and Feb 15) — nearly identical content, ~same headline | 2/5 episodes |
| T8 | MEDIUM | **European/China sales stories repeated** on consecutive days (Feb 12-13) | 2/5 episodes |
| T9 | MEDIUM | **First Principles topics cluster** — energy storage themes appear twice in 5 days. Root cause: `extract_sections_from_digest()` has NO regex for First Principles, so tracker is always empty | 2/5 episodes |
| T10 | MEDIUM | **Daily Challenges cluster** — 3 "optimize/streamline a routine" challenges in 4 days. Tracker provides history but Grok doesn't differentiate themes | 3/5 episodes |
| T11 | MEDIUM | **Identical stock price on Feb 14 & 15** ($417.44 +1.11) — weekend market closed, no acknowledgment | 2/5 episodes |
| T12 | MEDIUM | **change_str `+1.11` lacks `$` sign** — TTS reads "up one point one one" instead of "up one dollar and eleven cents" | All episodes |

### OMNI VIEW — 7 Issues (2 CRITICAL, 3 HIGH, 2 MEDIUM)

| # | Severity | Issue | Frequency |
|---|----------|-------|-----------|
| O1 | CRITICAL | **Broken currency conversion** — Feb 11: Mistral AI story produces "one point four two nine nine nine nine nine nine nine..." (floating-point precision bug in number_to_words). Garbled audio. | 1/5 episodes |
| O2 | CRITICAL | **Triple-duplicate in single episode** — Feb 13: Palestine Action court ruling appears 3 times (from 3 different sources, not deduped) | 1/5 episodes |
| O3 | HIGH | **Munich Security Conference dominates 4/5 episodes** — same multi-day event recycled daily with incremental angles | 4/5 episodes |
| O4 | HIGH | **Palestine Action Ban spans 3 episodes** — ~15% of total podcast time on one UK legal dispute | 3/5 episodes |
| O5 | HIGH | **No cross-episode dedup exists** — zero tracking code in omni_view.py | Structural |
| O6 | MEDIUM | **~40% single-source stories** — violates "balanced perspectives" mission statement | 5/5 episodes |
| O7 | MEDIUM | **Low-substance filler** — "digestion tips", "bobsled tech" in a news podcast | 3/5 episodes |

### FASCINATING FRONTIERS — 7 Issues (2 CRITICAL, 3 HIGH, 2 MEDIUM)

| # | Severity | Issue | Frequency |
|---|----------|-------|-----------|
| F1 | CRITICAL | **Only 2 unique quotes in 5 episodes** — Einstein quote 3 times, Sagan quote 2 times | 5/5 episodes |
| F2 | CRITICAL | **Crew-12 covered 13+ times across 5 episodes** — 4 separate stories about the same launch in Feb 14 episode alone | 5/5 episodes |
| F3 | HIGH | **Same-episode duplicates** — Feb 12: identical Crew-12 insignia photo as 2 stories. Feb 10: SpaceX Moon pivot as 2 stories. Feb 6: NGC 7722 galaxy as 2 stories. | 4/5 episodes |
| F4 | HIGH | **Feb 14: first 3 stories are the same Crew-12 launch** from different sources (NASA, Space.com, Spaceflight Now) | 1/5 episodes |
| F5 | HIGH | **No cross-episode dedup exists** — zero tracking code in fascinating_frontiers.py | Structural |
| F6 | MEDIUM | **Mars dominates Cosmic Spotlight** — 3/5 spotlights are Mars topics | 3/5 episodes |
| F7 | MEDIUM | **TTS hazards** — raw "GW250114", "USSF-87" acronyms not pre-processed for pronunciation | 2/5 episodes |

### PLANETTERRIAN DAILY — 8 Issues (2 CRITICAL, 4 HIGH, 2 MEDIUM)

| # | Severity | Issue | Frequency |
|---|----------|-------|-----------|
| P1 | CRITICAL | **Exact duplicate story across episodes** — pig liver xenotransplantation in Feb 9 AND Feb 11, same source | 2/5 episodes |
| P2 | CRITICAL | **Exact duplicate story across episodes** — Jim O'Neill vaccine guidelines in Feb 13 AND Feb 15 | 2/5 episodes |
| P3 | HIGH | **Virgil quote used 3 times** — exact "The greatest wealth is health" in Feb 7 and Feb 15; adapted variant in Feb 9 | 3/5 episodes |
| P4 | HIGH | **Says "Top 15" but always delivers 12** — consistent across all 5 episodes | 5/5 episodes |
| P5 | HIGH | **Same-episode topic clustering** — Feb 13: 3 COVID vaccine stories (nearly identical from different journals) | 1/5 episodes |
| P6 | HIGH | **No cross-episode dedup exists** — zero tracking code in planetterrian.py | Structural |
| P7 | MEDIUM | **Alzheimer's stories 4 times in 4 episodes** — excessive clustering on one disease area | 4/5 episodes |
| P8 | MEDIUM | **TTS number hazards** — "$23.17 billion", "8.5% CAGR", "PD-1" acronyms | 2/5 episodes |

### ENVIRONMENTAL INTELLIGENCE — 6 Issues (all pre-launch, code-level)

| # | Severity | Issue | Frequency |
|---|----------|-------|-----------|
| E1 | CRITICAL | **No cross-episode dedup in engine** — `engine/tracking.py` only tracks costs, not content history. `engine/fetcher.py` uses `remove_similar_items()` within one fetch only. | Structural |
| E2 | HIGH | **24-hour cutoff with no fallback** — `run_show.py` line 169 uses `cutoff_hours=24`. On weekends/holidays (Env Intel covers BC government feeds that don't publish weekends), this will return 0 articles and silently exit | Structural |
| E3 | HIGH | **No post-generation validation** — `engine/generator.py` returns Grok output without checking section structure, article count, or content quality | Structural |
| E4 | MEDIUM | **No section overlap checking** — Env Intel has 3 news sections (Regulatory, Science, Industry). Nothing checks that Grok put different stories in each | Structural |
| E5 | MEDIUM | **filter_articles_by_recent_stories() exists in engine/utils.py but is never called by run_show.py** — the cross-day dedup function is written but not wired up | Structural |
| E6 | LOW | **No shows/hooks/env_intel.py** — no pre-fetch hook for Env-Intel-specific logic (e.g., Canada Gazette filtering, BC-specific keyword boosting) | Structural |

---

## Part 2: Root Causes

Every issue above traces to one of these **7 root causes**:

### RC1: No post-generation validation (affects ALL shows)

After Grok generates a digest, the code saves it and moves to TTS. There is **zero validation** that:
- Sections don't duplicate each other (Top 10 vs Takeover, Regulatory vs Science)
- Content differs from recent episodes
- Article counts meet stated requirements ("Top 10" actually has 10)
- Forbidden content was excluded (stock prices in TST podcast)
- Short Spot uses a unique article

**Issues caused:** T1, T2, T4, T5, O2, F3, F4, P5, E3, E4

### RC2: OV/FF/PT/EI have no cross-episode content tracking (affects 4 of 5 shows)

Only TST has `load_used_content_tracker()` / `load_recent_digests()` / `save_used_content_tracker()`. The other 4 shows have zero cross-episode memory.

**Issues caused:** O3, O4, O5, F2, F5, P1, P2, P6, E1

### RC3: TST's First Principles extraction is broken (affects TST)

`extract_sections_from_digest()` (line 264-313) has no regex for `🧠 Tesla First Principles`. The `first_principles` tracker key is initialized but never populated. Grok gets empty history.

**Issues caused:** T9

### RC4: Same-day dedup only checks title similarity at 85% — not topics or entities (affects ALL shows)

`remove_similar_items()` compares `title + description` strings. Two articles about the same event from different sources (different titles) pass the 85% check. Crew-12 from Space.com vs NASA.gov vs Spaceflight Now all have <85% title similarity yet cover the identical event.

**Issues caused:** F2, F3, F4, O2, P5

### RC5: Prompt contradictions that Grok cannot resolve (affects TST, PT)

- TST: "Narrate EVERY item from the digest in order" + "Do NOT mention TSLA stock price" — the stock price IS in the digest
- TST: "Top 10 and Takeover must have ZERO overlap" — when <15 articles exist, Grok has no choice
- PT: Prompt says "Top 15" but typically only 12 articles are available

**Issues caused:** T1, T2, T4, P4

### RC6: No weekend/low-news handling (affects ALL shows)

No code detects weekends, holidays, or sparse-news periods. No adaptive cutoff expansion, no "recap" episode format, no skip logic.

**Issues caused:** T6, T7, T8, T11, O3, F2, E2

### RC7: Pronunciation formatting gaps (affects ALL shows)

- TST `change_str` uses `+1.11` (bare number) instead of `+$1.11` (signed currency)
- OV has floating-point precision bug producing repeated "nine" digits
- Scientific acronyms pass through TTS without phonetic expansion

**Issues caused:** T12, O1, F7, P8

---

## Part 3: Comprehensive Fix Plan

### Phase 1: `engine/content_tracker.py` — Cross-Episode Dedup for All Shows

**Fixes:** RC2, RC3 (T6-T10, O3-O5, F1-F2, F5-F6, P1-P3, P6-P7, E1)
**Effort:** Medium | **Impact:** HIGH — prevents story/quote repetition across episodes

Create a shared content-history module that all 5 shows use:

```python
class ContentTracker:
    def __init__(self, show_slug, output_dir, max_days=14):
        self.tracker_file = output_dir / f"{show_slug}_content_tracker.json"
        # Tracks: headlines, section content (spotlight, short spot, etc.),
        # quotes, challenge themes

    def load(self):
        """Load tracker JSON + scan recent digest files for backup."""

    def extract_sections(self, digest_path, section_patterns):
        """Extract all sections using show-specific regex patterns.
        Each show provides its own pattern dict."""

    def get_recent_headlines(self, days=14):
        """Return recent headlines for cross-day dedup."""

    def get_summary_for_prompt(self, limits=None):
        """Generate 'RECENTLY USED...' block for Grok prompt."""

    def check_quote_reuse(self, new_quote, window_days=30):
        """Check if quote author appeared within window."""

    def save(self, new_sections):
        """Persist updated tracker, prune old entries."""
```

**Per-show section patterns:**
- **TST:** `short_spot`, `first_principles` (FIXING RC3), `daily_challenge`, `inspiration_quote`, `market_movers`
- **FF:** `cosmic_spotlight`, `daily_inspiration` (with 30-day quote window)
- **PT:** `planetterrian_spotlight`, `daily_inspiration` (with 30-day quote window)
- **OV:** Story headlines per category section
- **EI:** `lead_story`, `regulatory_watch`, `science_technical`, `industry_practice`, `action_items`

**Integration:** Both `run_show.py` (new shows) and the 4 legacy scripts call the same tracker.

### Phase 2: `engine/validation.py` — Post-Generation Guard

**Fixes:** RC1 (T1, T2, T4, T5, O2, F3, F4, P5, E3, E4)
**Effort:** Medium | **Impact:** HIGH — catches within-episode duplication before TTS

```python
def validate_digest(digest_text, config, recent_tracker=None):
    """Master validator. Returns (passed: bool, issues: list[str])."""

    issues = []

    # 1. Section overlap: compare headlines between section pairs
    #    e.g., Top 10 vs Takeover, Regulatory vs Science vs Industry
    overlap = check_section_overlap(digest_text, config.section_pairs)
    if overlap:
        issues.append(f"Section overlap: {overlap}")

    # 2. Story count: verify each section has expected item count
    for section in config.sections:
        count = count_items_in_section(digest_text, section.name)
        if count < section.min_items:
            issues.append(f"{section.name}: {count} items (min {section.min_items})")

    # 3. Forbidden content (e.g., stock prices in TST podcast script)
    for pattern in config.forbidden_patterns:
        if re.search(pattern, digest_text):
            issues.append(f"Forbidden content found: {pattern}")

    # 4. Cross-episode dedup (if tracker provided)
    if recent_tracker:
        repeats = check_against_history(digest_text, recent_tracker, threshold=0.65)
        if repeats:
            issues.append(f"Repeated from recent episodes: {repeats}")

    # 5. Quote/challenge reuse
    ...

    return (len(issues) == 0, issues)
```

If critical issues found, the pipeline can:
1. Log warnings and continue (soft mode)
2. Regenerate with a corrective prompt appended: "The previous output had overlapping sections. Please ensure..." (retry mode — up to 1 retry)

### Phase 3: Fix Prompt Contradictions

**Fixes:** RC5 (T1, T2, T4, P4)
**Effort:** Low | **Impact:** HIGH — eliminates root cause of TST's worst issues

**3a. TST: Remove stock price from podcast input**
Strip `**TSLA:** $price change_str` from `x_thread` before passing to `POD_PROMPT`. The stock price belongs in the X post and markdown only, not the podcast generation context.

**3b. TST: Make Takeover conditional on article count**
Replace the hard "Top 10 + 5 Takeover" with:
```
If {article_count} >= 15: produce Top 10 News + 5 Tesla X Takeover (ZERO overlap)
If {article_count} >= 8 and < 15: produce Top {article_count} News (no Takeover section)
If {article_count} < 8: produce all available news items (no Takeover section)
```

**3c. TST: Decouple Short Spot**
Add: "Short Spot MUST use an article whose URL does NOT appear in the Top News section. If no separate bearish article exists, skip Short Spot this episode."

**3d. TST: Rename "Top 10" to "Top News"**
Remove the hard count from the label. Let Grok produce quality over quantity.

**3e. PT: Change "Top 15" to "Top 12"**
Match the actual consistent output.

**3f. All shows: Insert article count into prompt**
Dynamically: "You have {n} quality articles to work with."

### Phase 4: Improve Same-Day Dedup — Entity-Level

**Fixes:** RC4 (F2, F3, F4, O2, P5)
**Effort:** Medium | **Impact:** HIGH — prevents 4x Crew-12 type clustering

Enhance `engine/utils.py`:

**4a. URL dedup** — If two articles share the same URL (or same base domain + path), they're the same article.

**4b. Entity extraction dedup** — Before sending articles to Grok, extract key entities (mission names, person names, organization names) and flag when >2 articles share the same primary entity.
```python
def extract_primary_entity(title: str, description: str) -> str:
    """Extract the main subject (Crew-12, Palestine Action, Jim O'Neill, etc.)"""
    # Simple approach: longest proper noun phrase in title
    # Advanced: use Grok to tag entities in a lightweight call
```

**4c. Lower cross-source threshold** — If two articles from different RSS feeds share the same primary entity AND >50% description similarity, drop one.

**4d. Topic diversity cap** — Maximum 2 articles per primary entity in the final selection. If Crew-12 has 6 articles, only the 2 most distinct survive.

### Phase 5: Weekend/Low-News Handling

**Fixes:** RC6 (T6, T7, T8, T11, O3, F2, E2)
**Effort:** Low | **Impact:** MEDIUM

**5a. Adaptive cutoff expansion** — In `run_show.py` and legacy scripts:
```python
cutoff_hours = 24
articles = fetch_rss_articles(..., cutoff_hours=cutoff_hours)
if len(articles) < 5:
    cutoff_hours = 48
    articles = fetch_rss_articles(..., cutoff_hours=cutoff_hours)
if len(articles) < 5:
    cutoff_hours = 72
    articles = fetch_rss_articles(..., cutoff_hours=cutoff_hours)
```

**5b. Weekend detection** — `is_low_news_day()` checks `weekday >= 5` and major holidays.

**5c. Editorial strategy** — When detected as low-news:
- Adjust prompt: "This is a weekend edition. Focus on analysis and context rather than breaking news."
- TST: Skip Takeover section entirely
- All: Allow "week in review" or "what to watch next week" format

**5d. TST stock price weekend awareness** — When market is closed, change display to: `**TSLA:** $417.44 (Market closed — Friday close)` instead of showing a misleading `+1.11 (+0.27%)`.

### Phase 6: Pronunciation Fixes

**Fixes:** RC7 (T12, O1, F7, P8)
**Effort:** Low | **Impact:** MEDIUM

**6a. TST change_str format** — Change line 218:
```python
# Before:
change_str = f"{change:+.2f} ({change_pct:+.2f}%)"
# After:
sign = "+" if change > 0 else "-"
change_str = f"{sign}${abs(change):.2f} ({change_pct:+.2f}%)"
```
So `+$1.11` → `replace_signed_currency()` → "up one dollar and eleven cents"

**6b. OV number_to_words precision bug** — Add rounding before conversion:
```python
# In number_to_words() or the OV caller:
value = round(float(num_str), 2)  # Prevent 1.4299999999994 artifacts
```

**6c. Add scientific acronyms to pronunciation.py**:
```python
COMMON_ACRONYMS.update({
    "USSF": "U S S F",
    "PROTAC": "pro-tack",
    "ARPA-H": "arpa H",
    "CAGR": "C A G R",
    "CEPA": "see-pa",
    "EMA": "E M A",
    "CCME": "C C M E",
    "SVE": "S V E",
})
```

**6d. Host name stripping** — In `_clean_podcast_script()` and TST's script processor:
```python
text = re.sub(r"\bI'm Patrick\b", "I'm your host", text)
text = re.sub(r"\bPatrick here\b", "Your host here", text)
text = re.sub(r"\bI'm Patrick [\w, ]+\.", "I'm your host.", text)
```

### Phase 7: Quote/Challenge Diversity Enforcement

**Fixes:** F1, P3, T10
**Effort:** Low | **Impact:** MEDIUM

Built into Phase 1's ContentTracker:

- **Inspiration quotes**: No author repeat within 30 days. `check_quote_reuse()` returns True if same author appeared within window. If Grok repeats an author, post-generation validation (Phase 2) flags it.
- **Daily challenges**: Track the "theme keyword" (optimize, streamline, declutter, energy, etc.) and require 7+ days between same themes.
- **First Principles (TST)**: Track the core topic keyword (energy storage, aerodynamics, UI design, etc.) and require 14+ days between similar topics.
- **Cosmic Spotlight (FF) / Planetterrian Spotlight (PT)**: Track topic and require 3+ episodes between same topic area.

---

## Part 4: Implementation Priority

| Priority | Phase | What | Effort | Shows Fixed | Issues Fixed |
|----------|-------|------|--------|-------------|--------------|
| **1** | Phase 1 | `engine/content_tracker.py` — cross-episode dedup | Medium | All 5 | 15 issues |
| **2** | Phase 2 | `engine/validation.py` — post-generation guard | Medium | All 5 | 10 issues |
| **3** | Phase 3 | Fix prompt contradictions | Low | TST, PT | 5 issues |
| **4** | Phase 6 | Pronunciation fixes | Low | All 5 | 4 issues |
| **5** | Phase 4 | Entity-level same-day dedup | Medium | All 5 | 5 issues |
| **6** | Phase 5 | Weekend/low-news handling | Low | All 5 | 7 issues |
| **7** | Phase 7 | Quote/challenge diversity | Low | TST, FF, PT | 3 issues |

**Total issues identified: 40 across 5 shows**
**Total unique root causes: 7**
**Phases 1-3 alone fix ~30 of 40 issues (75%)**

---

## Part 5: Environmental Intelligence Pre-Launch Checklist

Before EI's first episode, these items must be addressed:

- [ ] **Wire up cross-day dedup** — Call `filter_articles_by_recent_stories()` from `run_show.py` (function exists in `engine/utils.py` but is not called)
- [ ] **Add adaptive cutoff expansion** — `cutoff_hours=24` is too tight for BC government feeds on weekends
- [ ] **Create `shows/hooks/env_intel.py`** — Even if empty initially, needed for future pre-fetch logic
- [ ] **Add post-generation validation** — Ensure 3 distinct sections (Regulatory, Science, Industry) have non-overlapping content
- [ ] **Test on a weekend** — Run `python run_show.py env_intel --test` on a Saturday to verify it handles low-news gracefully
- [ ] **Set `ENV_INTEL_NEWSLETTER_API_KEY`** — Newsletter is enabled but will silently skip if key is missing
- [ ] **Add EI-specific acronyms to pronunciation.py** — CSR, EMA, CEPA, CCME, SVE, ESA, PFAS, etc.
