# FINDINGS — Tesla X Fetch Quick Wins

Issues noticed during implementation that are out of scope for this branch
but worth addressing in future work.

## 1. Web search keyword filter has the same seed-account problem

`fetch_web_search_articles` (fetcher.py:746-758) also applies a post-retrieval
keyword filter. This is less of an issue for web search (queries are topical
by construction), but for consistency the filter should be optional and
controllable per-show. Left untouched in this branch.

## 2. Pre-dedup cap sorts by arrival order, not quality

`run_show.py:659-665` caps articles at 150 before dedup but uses slice
(`articles[:150]`), which preserves arrival order (RSS first, then X, then
web search). After Fix 5's relevance sort, this happens BEFORE the sort,
so high-relevance X posts could be dropped if RSS returns 150+ articles.
Consider moving the pre-dedup cap after the relevance sort, or applying
the sort earlier.

## 3. `_parse_x_posts` regex is fragile

The `POST_TITLE / POST_TEXT / POST_URL` extraction relies on Grok following
the exact structured format. If Grok adds commentary, numbering, or
markdown formatting around the blocks, the regex silently misses posts.
A more robust parser (e.g. splitting on numbered items or using JSON output
mode) would reduce silent data loss.

## 4. No dedup between X accounts

If @sawyermerrit and @wholemarsblog both quote-tweet the same Musk
announcement, both posts enter the pipeline. The X/RSS cross-dedup at
run_show.py:495-521 only compares X posts against RSS — not X against X.
A lightweight pairwise dedup among X posts (same threshold) would help.

## 5. `grok_generate_text` doesn't surface tool-use metadata

The `meta` dict returned by `grok_generate_text` doesn't indicate whether
Grok actually invoked `x_search` vs answering from priors. When `max_turns`
is tight, Grok sometimes skips the tool call and hallucinates posts. Adding
a `tool_calls_made` field to the metadata would let callers detect and retry.

## 6. Tesla YAML has no `@elonmusk` in x_accounts

The three configured accounts (sawyermerrit, tslaming, wholemarsblog) are
Tesla commentary accounts. Elon's own account (@elonmusk) is not included,
so direct Musk posts are only captured if they appear in replies or quote
tweets from these three. Adding @elonmusk as a seed account (with a high
`max_posts`) would capture primary-source announcements directly.
