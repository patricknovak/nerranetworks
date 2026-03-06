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
            # =============================================================
            # AI and ML core terms (override shared COMMON_ACRONYMS)
            # =============================================================
            # Compound forms MUST come before bare "AI" to match first.
            "AI-powered": "ay-eye-powered",
            "AI-driven": "ay-eye-driven",
            "AI-based": "ay-eye-based",
            "AI-generated": "ay-eye-generated",
            "AI-first": "ay-eye-first",
            "AI-native": "ay-eye-native",
            "AI-enabled": "ay-eye-enabled",
            "AI-ready": "ay-eye-ready",
            "AI-augmented": "ay-eye-augmented",
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
            "SFT": "ess-eff-tee",
            "RLHF": "are-ell-aitch-eff",
            "DPO": "dee-pee-oh",
            "SOTA": "so-tah",
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
            "LoRAs": "lauras",
            "CUDA": "koodah",
            "VRAM": "vee-ram",
            "FLOPS": "flops",
            "FP16": "eff-pee-sixteen",
            "FP32": "eff-pee-thirty-two",
            "INT8": "int-eight",
            "INT4": "int-four",
            "GGUF": "gee-guff",
            "ONNX": "onyx",
            "QLoRA": "cue-laura",

            # =============================================================
            # Model names and versions
            # =============================================================
            "Claude": "Klawd",
            "Claude's": "Klawd's",
            "Gemini": "Jemminye",
            "Gemini's": "Jemminye's",
            "Llama": "Lahmah",
            "Llama's": "Lahmah's",
            "Mistral": "Mistral",
            "Mistral's": "Mistral's",
            "Mixtral": "Mix-tral",
            "Grok": "Grock",
            "Grok's": "Grock's",
            "DALL-E": "Dolly",
            "DALL·E": "Dolly",
            "Sora": "Sorah",
            "Qwen": "Chwen",
            "Qwen's": "Chwen's",
            "DeepSeek": "Deep Seek",
            "DeepSeek's": "Deep Seek's",
            "Phi-3": "Fie three",
            "Phi-4": "Fie four",
            "Stable Diffusion": "Stable Diffusion",
            "Midjourney": "Mid-journey",
            "Midjourney's": "Mid-journey's",
            "Perplexity": "Per-plexity",
            "Copilot": "Co-pilot",
            "ChatGPT": "Chat gee-pee-tee",
            "ChatGPT's": "Chat gee-pee-tee's",
            "GPT-2": "gee-pee-tee two",
            "Opus": "Oh-pus",
            "Sonnet": "Son-ett",
            "Haiku": "Hi-koo",
            "Whisper": "Whisper",
            "Runway": "Run-way",
            "Runway's": "Run-way's",
            "Canva": "Can-vah",
            "Canva's": "Can-vah's",
            "Groq": "Grock",
            "Groq's": "Grock's",
            "NVIDIA": "en-Vidya",
            "Nvidia": "en-Vidya",
            "Nvidia's": "en-Vidya's",

            # =============================================================
            # Org names espeak may mangle
            # =============================================================
            "GitHub": "Git Hub",
            "GitHub's": "Git Hub's",
            "GitLab": "Git Lab",
            "HuggingFace": "Hugging Face",
            "Hugging Face": "Hugging Face",
            "LangChain": "Lang Chain",
            "LangChain's": "Lang Chain's",
            "LangGraph": "Lang Graph",
            "LangGraph's": "Lang Graph's",
            "LlamaIndex": "Lahmah Index",
            "AutoGPT": "Auto gee-pee-tee",
            "AutoGen": "Auto-Jen",
            "CrewAI": "Crew ay-eye",
            "CrewAI's": "Crew ay-eye's",
            "Anthropic": "Ann-thropic",
            "Anthropic's": "Ann-thropic's",
            "Sakana": "Sah-kah-nah",
            "Sakana's": "Sah-kah-nah's",
            "arXiv": "archive",
            "ArXiv": "archive",
            "Kaggle": "Kagg-ul",
            "Colab": "Co-lab",
            "PyTorch": "Pie-Torch",
            "TensorFlow": "Tensor Flow",
            "Replicate": "Replicate",
            "Gradio": "Grah-dee-oh",

            # =============================================================
            # Common tech acronyms
            # =============================================================
            "URLs": "you-are-ells",
            "URL": "you-are-ell",
            "CLI": "see-ell-eye",
            "IDE": "eye-dee-ee",
            "UI": "you-eye",
            "UX": "you-ex",
            "SaaS": "sass",
            "IoT": "eye-oh-tee",
            "JSON": "jay-son",
            "YAML": "yam-ul",
            "OAuth": "oh-auth",
            "HTML": "aitch-tee-em-ell",
            "CSS": "see-ess-ess",
            "AWS": "ay-double-you-ess",
            "GCP": "jee-see-pee",
            "VM": "vee-em",
            "VMs": "vee-ems",
            "PR": "pee-are",

            # =============================================================
            # Benchmark names that sound weird read literally
            # =============================================================
            "GSM8K": "gee-ess-em eight-kay",
            "GSM8k": "gee-ess-em eight-kay",
            "MMLU": "em-em-ell-you",
            "HumanEval": "Human Eval",
            "HellaSwag": "Hella-Swag",
            "ARC-C": "arc see",
            "MATH": "math",
            "GPQA": "gee-pee-cue-ay",

            # =============================================================
            # Beginner-show-specific terms the host uses often
            # =============================================================
            "TTS": "tee-tee-ess",
            "OCR": "oh-see-are",
            "GAN": "gan",
            "GANs": "gans",
            "VAE": "vee-ay-ee",
            "CNN": "see-en-en",
            "RNN": "are-en-en",
            "BERT": "bert",
            "GPT-3": "gee-pee-tee three",
            "GPT-3.5": "gee-pee-tee three point five",
            "3D": "three-dee",
            "2D": "two-dee",
            "4K": "four-kay",
            "8K": "eight-kay",

            # =============================================================
            # Common spoken-word fixes for Kokoro/espeak quirks
            # =============================================================
            "i.e.": "that is",
            "e.g.": "for example",
            "etc.": "et cetera",
            "vs.": "versus",
            "vs": "versus",
            "w/": "with",
            "w/o": "without",
        },

        # Extra word pronunciations for proper names Kokoro may mangle.
        "extra_words": {
            "Karpathy": "Kar-pathy",
            "Karpathy's": "Kar-pathy's",
            "Andrej": "On-dray",
            "Sutskever": "Suts-kever",
            "Altman": "Alt-man",
            "Hassabis": "Ha-sah-bis",
            "LeCun": "Luh-Kuhn",
            "Vaswani": "Vaz-wah-nee",
            "Hinton": "Hinton",
            "Bengio": "Ben-jee-oh",
            "Amodei": "Ah-mo-day",
            "tokenizer": "token-eye-zer",
            "tokenizers": "token-eye-zers",
            "tokenize": "token-eyes",
            "tokenized": "token-eyzed",
            "multimodal": "multi-modal",
            "hyperparameter": "hyper-parameter",
            "hyperparameters": "hyper-parameters",
            "overfitting": "over-fitting",
            "underfitting": "under-fitting",
            "backpropagation": "back-propagation",
            "embeddings": "em-beddings",
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
            "workflow": "work flow",
            "workflows": "work flows",
        },
    }
