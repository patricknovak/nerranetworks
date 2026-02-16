# Shared Assets for Podcasts

This directory contains permanent, reusable assets for all podcasts.

## Directory Structure

```
assets/
├── pronunciation.py         # Shared pronunciation dictionary module
└── README.md               # This file
```

## Pronunciation Dictionary

### What is the Pronunciation Dictionary?

The `pronunciation.py` module contains shared pronunciation fixes for acronyms, names, and terms that TTS engines commonly mispronounce. This avoids duplicating pronunciation logic across multiple podcast scripts.

### Using the Shared Pronunciation Dictionary

```python
from assets.pronunciation import apply_pronunciation_fixes, COMMON_ACRONYMS

# Apply all default fixes
text = apply_pronunciation_fixes(text)

# Apply with custom dictionaries
text = apply_pronunciation_fixes(
    text,
    acronyms=COMMON_ACRONYMS,
    use_zwj=False  # Use spaces instead of zero-width joiners
)
```

### Adding New Pronunciations

Edit `assets/pronunciation.py` to add new terms:

```python
# Add to COMMON_ACRONYMS
COMMON_ACRONYMS["NEW_ACRONYM"] = "N E W A C R O N Y M"

# Add to PLAYER_NAMES
PLAYER_NAMES["Player Name"] = "Player Pro nun ci a tion"
```

## Benefits

- **Consistent Voice** - Shared pronunciation fixes across all podcasts
- **Version Control** - Pronunciation fixes are tracked in git
- **Easy Updates** - Update pronunciation once, affects all podcasts
