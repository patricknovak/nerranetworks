# Newsletter Platform Comparison

> Evaluated Feb 2026 for automated daily podcast newsletter sending.

## Requirements
- Send emails programmatically via API (not manual UI)
- Support 5 separate newsletters (one per show)
- Free or very cheap tier
- Daily sending frequency

## Comparison

| Feature | Buttondown | Beehiiv | Kit (ConvertKit) | Substack |
|---------|-----------|---------|------------------|----------|
| Free subscribers | 100 | 2,500 | ~10,000 | Unlimited |
| API send on free tier | **Yes** | No (Enterprise) | Yes | No API |
| Multi-newsletter | **Yes (native)** | Yes (3 on free) | No (tags hack) | Yes |
| RSS-to-email on free | **Yes** | No (Max+) | No (Creator+) | No |
| Send endpoint | `POST /v1/emails` | `POST /v2/.../posts` | `POST /v4/broadcasts` | N/A |
| Auth | `Token` header | `Bearer` token | API Key header | N/A |
| Cheapest paid | $9/mo | $43/mo | $33/mo | Free (10% rev) |

## Recommendation: Buttondown

- Full API access on free tier
- Native multi-newsletter support (deduped billing)
- RSS-to-email backup option
- Markdown support in API
- `POST /v1/emails` with `{"subject": "...", "body": "...", "status": "about_to_send"}`

## Disqualified
- **Beehiiv**: Send API requires Enterprise plan
- **Substack**: No API at all
- **Kit**: No true multi-publication (tags/segments workaround is fragile)
