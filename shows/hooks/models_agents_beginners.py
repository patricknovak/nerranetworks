"""Models & Agents for Beginners — pronunciation hook for Chatterbox TTS.

Chatterbox is a neural TTS model that handles standard English pronunciation
well on its own.  Only override words that Chatterbox genuinely mispronounces.

**Key principle:** Do NOT override common English words or well-known names
(Gemini, Claude, Llama, Grok, DALL-E) — Chatterbox pronounces these correctly
natively.  Only override obscure acronyms, non-English names, and compound
words that need splitting.
"""

from __future__ import annotations


def pronunciation_overrides() -> dict:
    """Return Chatterbox-friendly phonetic overrides for AI/ML terms.

    Called by ``run_show.py:_apply_pronunciation()`` to customize the
    shared ``prepare_text_for_tts()`` pipeline.
    """
    return {
        # Extra acronyms not in the shared COMMON_ACRONYMS or where
        # Chatterbox needs a specific phonetic hint.
        "extra_acronyms": {
            # AI compound forms — ensure "AI" is always spelled out
            "AI-powered": "A I powered",
            "AI-driven": "A I driven",
            "AI-based": "A I based",
            "AI-generated": "A I generated",
            "AI-first": "A I first",
            "AI-native": "A I native",
            "AI-enabled": "A I enabled",
            "AI-ready": "A I ready",
            "AI-augmented": "A I augmented",

            # Org/product compound names with AI
            "OpenAI's": "Open A I's",
            "OpenAI": "Open A I",
            "GenAI": "Jen A I",
            "xAI's": "ex A I's",
            "xAI": "ex A I",
            "CrewAI": "Crew A I",
            "CrewAI's": "Crew A I's",
            "AutoGPT": "Auto G P T",
            "AutoGen": "Auto-Jen",
            "ChatGPT": "Chat G P T",
            "ChatGPT's": "Chat G P T's",

            # Model version names
            "GPT-4o": "G P T four oh",
            "GPT-4": "G P T four",
            "GPT-5": "G P T five",
            "GPT-3.5": "G P T three point five",
            "GPT-3": "G P T three",
            "GPT-2": "G P T two",

            # Obscure acronyms that need phonetic hints
            "SOTA": "so-tah",
            "LoRA": "laura",
            "LoRAs": "lauras",
            "QLoRA": "cue-laura",
            "GGUF": "gee-guff",
            "ONNX": "onyx",
            "CUDA": "kooda",
            "VRAM": "vee-ram",
            "FP16": "F P sixteen",
            "FP32": "F P thirty-two",
            "INT8": "int eight",
            "INT4": "int four",

            # Benchmark names
            "GSM8K": "G S M eight K",
            "GSM8k": "G S M eight K",
            "HellaSwag": "Hella-Swag",
            "HumanEval": "Human Eval",

            # Common spoken-word fixes
            "i.e.": "that is",
            "e.g.": "for example",
            "etc.": "et cetera",
            "vs.": "versus",
            "vs": "versus",
            "w/": "with",
            "w/o": "without",
        },

        # Proper names and compound words Chatterbox may mangle.
        # NOTE: Do NOT add overrides for common English words that
        # Chatterbox handles natively (Gemini, Claude, Llama, etc.).
        "extra_words": {
            # AI researcher names (non-English, genuinely need help)
            "Karpathy": "Kar-pathy",
            "Karpathy's": "Kar-pathy's",
            "Andrej": "On-dray",
            "Sutskever": "Suts-kever",
            "Hassabis": "Ha-sah-bis",
            "LeCun": "Luh-Kuhn",
            "Vaswani": "Vaz-wah-nee",
            "Bengio": "Ben-jee-oh",
            "Amodei": "Ah-mo-day",

            # Model and org names (only non-English or compound words)
            "Mixtral": "Mix-tral",
            "Groq": "Grock",
            "Groq's": "Grock's",
            "Qwen": "Chwen",
            "Qwen's": "Chwen's",
            "DeepSeek": "Deep Seek",
            "DeepSeek's": "Deep Seek's",
            "Phi-3": "Fie three",
            "Phi-4": "Fie four",
            "Midjourney": "Mid-journey",
            "Midjourney's": "Mid-journey's",
            "Sakana": "Sah-kah-nah",
            "Sakana's": "Sah-kah-nah's",
            "Gradio": "Grah-dee-oh",
            "LlamaIndex": "Llama Index",
            "LangChain": "Lang Chain",
            "LangChain's": "Lang Chain's",
            "LangGraph": "Lang Graph",
            "LangGraph's": "Lang Graph's",
            "HuggingFace": "Hugging Face",
            "PyTorch": "Pie Torch",
            "TensorFlow": "Tensor Flow",
            "arXiv": "archive",
            "ArXiv": "archive",

            # AI/ML compound words (split for clearer TTS)
            "tokenizer": "token-izer",
            "tokenizers": "token-izers",
            "tokenize": "token-ize",
            "tokenized": "token-ized",
            "multimodal": "multi-modal",
            "hyperparameter": "hyper-parameter",
            "hyperparameters": "hyper-parameters",
            "overfitting": "over-fitting",
            "underfitting": "under-fitting",
            "backpropagation": "back-propagation",
            "finetune": "fine-tune",
            "finetuned": "fine-tuned",
            "finetuning": "fine-tuning",
            "fine-tuning": "fine tuning",
            "pretraining": "pre-training",
            "pre-trained": "pre trained",
            "opensource": "open source",
            "open-source": "open source",
            "open-sourced": "open sourced",
            "dataset": "data set",
            "datasets": "data sets",
            "codebase": "code base",
        },
    }
