# Shared Assets for Podcasts

This directory contains permanent, reusable assets for all podcasts to avoid recreating them each time.

## Directory Structure

```
assets/
├── voice_prompts/          # Permanent Chatterbox voice prompt files
│   └── patrick_voice_prompt.wav  # Example: permanent voice clone
├── pronunciation.py         # Shared pronunciation dictionary module
└── README.md               # This file
```

## Voice Prompts

### What are Voice Prompts?

Voice prompts are short audio samples (typically 5-10 seconds) used by Chatterbox TTS to clone your voice. Instead of extracting these from episode MP3s each time, you can create permanent voice prompt files that are reused across all podcast workflows.

### Creating a Permanent Voice Prompt

1. **Choose a high-quality episode** with clear voice (after intro music has faded)

2. **Generate the voice prompt**:
   ```bash
   python generate_voice_prompt.py digests/planetterrian/Planetterrian_Daily_Ep012_20251212.mp3 assets/voice_prompts/patrick_voice_prompt.wav
   ```

3. **Customize timing** (optional):
   ```bash
   # Start at 40 seconds (skip more intro music)
   VOICE_PROMPT_OFFSET=40 python generate_voice_prompt.py source.mp3 output.wav
   
   # Extract 15 seconds instead of default 10
   VOICE_PROMPT_DURATION=15 python generate_voice_prompt.py source.mp3 output.wav
   ```

4. **Commit the file** to the repository:
   ```bash
   git add assets/voice_prompts/patrick_voice_prompt.wav
   git commit -m "Add permanent voice prompt for Chatterbox"
   git push
   ```

### Using Permanent Voice Prompts

The podcast scripts automatically check for permanent voice prompts in this order:

1. `CHATTERBOX_VOICE_PROMPT_PATH` environment variable (highest priority)
2. `CHATTERBOX_VOICE_PROMPT_BASE64` environment variable
3. **Permanent voice prompt in `assets/voice_prompts/`** ← **Recommended**
4. Derive from existing episodes (fallback)

### Recommended Filenames

- `patrick_voice_prompt.wav` - For Patrick's voice (all podcasts)
- `voice_prompt.wav` - Generic fallback name
- `chatterbox_voice_prompt.wav` - Explicit Chatterbox prompt

Any `.wav` file in `assets/voice_prompts/` will be automatically detected and used.

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

✅ **Faster Workflows** - No need to extract voice prompts from episodes each time  
✅ **Consistent Voice** - Same voice prompt used across all podcasts  
✅ **Version Control** - Voice prompts and pronunciation fixes are tracked in git  
✅ **Easy Updates** - Update pronunciation once, affects all podcasts  
✅ **No Dependencies** - Permanent prompts don't require existing episodes  

## Best Practices

1. **Use permanent voice prompts** - Generate once, reuse forever
2. **Keep pronunciation dictionary updated** - Add new terms as needed
3. **Test voice prompts** - Ensure they produce good voice clones
4. **Commit assets** - Version control ensures consistency across environments

