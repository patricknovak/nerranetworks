"""Models & Agents for Beginners — pronunciation hook for Kokoro TTS.

Kokoro uses espeak for phonemization, which handles single-letter
expansions ("A I", "G P T") poorly — reading them as words instead
of spelling them out. This hook overrides the shared COMMON_ACRONYMS
with phonetic spellings that espeak pronounces correctly.

ElevenLabs handles "A I" fine because its TTS engine is trained on
letter sequences.  Kokoro/espeak needs "ay eye" style guides.
"""

from __future__ import annotations


def pronunciation_overrides() -> dict:
    """Return Kokoro-friendly phonetic overrides for AI/ML terms.

    Called by ``run_show.py:_apply_pronunciation()`` to customize the
    shared ``prepare_text_for_tts()`` pipeline.
    """
    return {
        # Override shared acronyms that use letter-spacing (broken in espeak)
        # with phonetic word forms that espeak reads naturally.
        "extra_acronyms": {
            # --- AI and ML (override shared COMMON_ACRONYMS) ---
            "AI-powered": "ay-eye-powered",
            "AI-driven": "ay-eye-driven",
            "AI-based": "ay-eye-based",
            "AI-generated": "ay-eye-generated",
            "AI-first": "ay-eye-first",
            "AI-native": "ay-eye-native",
            "AI-enabled": "ay-eye-enabled",
            "OpenAI's": "Open-ay-eye's",
            "OpenAI": "Open-ay-eye",
            "GenAI": "jen-ay-eye",
            "xAI's": "ex-ay-eye's",
            "xAI": "ex-ay-eye",
            "AI": "ay eye",
            "ML": "em-ell",
            "LLMs": "ell-ell-ems",
            "LLM": "ell-ell-em",
            "GPT-4o": "gee-pee-tee four oh",
            "GPT-4": "gee-pee-tee four",
            "GPT-5": "gee-pee-tee five",
            "GPT": "gee-pee-tee",
            "AGI": "ay-jee-eye",
            "NLP": "en-ell-pee",
            "RLHF": "are-ell-aitch-eff",
            "TPU": "tee-pee-you",
            "TPUs": "tee-pee-yous",
            "GPU": "jee-pee-you",
            "GPUs": "jee-pee-yous",
            "CPU": "see-pee-you",
            "CPUs": "see-pee-yous",
            "MCP": "em-see-pee",
            "APIs": "ay-pee-eyes",
            "API": "ay-pee-eye",
            "SDKs": "ess-dee-kays",
            "SDK": "ess-dee-kay",
            "RAG": "rag",
            "LoRA": "laura",
            "CUDA": "koodah",
            "RLHF": "are-ell-aitch-eff",

            # --- Common tech acronyms ---
            "URLs": "you-are-ells",
            "URL": "you-are-ell",
            "CLI": "see-ell-eye",
            "IDE": "eye-dee-ee",
            "UI": "you-eye",
            "UX": "you-ex",
            "SaaS": "sass",
            "IoT": "eye-oh-tee",

            # --- Model/company names espeak may mangle ---
            "Claude": "Klawd",
            "Gemini": "Jemminye",
            "Llama": "Lahmah",
            "Mistral": "Mistral",
            "Grok": "Grock",
            "DALL-E": "Dolly",
            "DALL·E": "Dolly",

            # --- Org names ---
            "GitHub": "Git Hub",
            "GitHub's": "Git Hub's",
            "HuggingFace": "Hugging Face",
            "LangChain": "Lang Chain",
            "LangGraph": "Lang Graph",
            "AutoGPT": "Auto gee-pee-tee",
            "CrewAI": "Crew ay-eye",
        },
    }
