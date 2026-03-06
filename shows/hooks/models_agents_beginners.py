"""Models & Agents for Beginners — pronunciation hook for Kokoro TTS.

Kokoro uses espeak for phonemization, which handles single-letter
expansions ("A I", "G P T") poorly — reading them as words instead
of spelling them out.  This hook uses **period-separated notation**
(e.g. "A.I.", "G.P.T.") which espeak reliably interprets as
abbreviations and spells letter-by-letter.

ElevenLabs handles space-separated letters ("A I") fine because its
TTS engine is trained on letter sequences.  Kokoro/espeak needs the
period notation to trigger its built-in abbreviation handling.

Word-like acronyms (RAG, BERT, CUDA, etc.) keep phonetic spellings
since they should be pronounced as words, not spelled out.
"""

from __future__ import annotations


def pronunciation_overrides() -> dict:
    """Return Kokoro-friendly phonetic overrides for AI/ML terms.

    Called by ``run_show.py:_apply_pronunciation()`` to customize the
    shared ``prepare_text_for_tts()`` pipeline.
    """
    return {
        # Override shared acronyms that use letter-spacing (broken in espeak)
        # with period-separated notation that espeak reads as abbreviations.
        "extra_acronyms": {
            # =============================================================
            # AI and ML core terms (override shared COMMON_ACRONYMS)
            # =============================================================
            # Compound forms MUST come before bare "AI" to match first.
            "AI-powered": "A.I. powered",
            "AI-driven": "A.I. driven",
            "AI-based": "A.I. based",
            "AI-generated": "A.I. generated",
            "AI-first": "A.I. first",
            "AI-native": "A.I. native",
            "AI-enabled": "A.I. enabled",
            "AI-ready": "A.I. ready",
            "AI-augmented": "A.I. augmented",
            "OpenAI's": "Open A.I.'s",
            "OpenAI": "Open A.I.",
            "GenAI": "Jen A.I.",
            "xAI's": "ex A.I.'s",
            "xAI": "ex A.I.",
            "AI": "A.I.",
            "ML": "M.L.",
            "LLMs": "L.L.M.s",
            "LLM": "L.L.M.",
            "GPT-4o": "G.P.T. four oh",
            "GPT-4": "G.P.T. four",
            "GPT-5": "G.P.T. five",
            "GPT": "G.P.T.",
            "AGI": "A.G.I.",
            "NLP": "N.L.P.",
            "SFT": "S.F.T.",
            "RLHF": "R.L.H.F.",
            "DPO": "D.P.O.",
            "SOTA": "so-tah",
            "TPU": "T.P.U.",
            "TPUs": "T.P.U.s",
            "GPU": "G.P.U.",
            "GPUs": "G.P.U.s",
            "CPU": "C.P.U.",
            "CPUs": "C.P.U.s",
            "MCP": "M.C.P.",
            "APIs": "A.P.I.s",
            "API": "A.P.I.",
            "SDKs": "S.D.K.s",
            "SDK": "S.D.K.",
            "RAG": "rag",
            "LoRA": "laura",
            "LoRAs": "lauras",
            "CUDA": "koodah",
            "VRAM": "vee-ram",
            "FLOPS": "flops",
            "FP16": "F.P. sixteen",
            "FP32": "F.P. thirty-two",
            "INT8": "int eight",
            "INT4": "int four",
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
            "ChatGPT": "Chat G.P.T.",
            "ChatGPT's": "Chat G.P.T.'s",
            "GPT-2": "G.P.T. two",
            "GPT-3": "G.P.T. three",
            "GPT-3.5": "G.P.T. three point five",
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
            "AutoGPT": "Auto G.P.T.",
            "AutoGen": "Auto-Jen",
            "CrewAI": "Crew A.I.",
            "CrewAI's": "Crew A.I.'s",
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
            "URLs": "U.R.L.s",
            "URL": "U.R.L.",
            "CLI": "C.L.I.",
            "IDE": "I.D.E.",
            "UI": "U.I.",
            "UX": "U.X.",
            "SaaS": "sass",
            "IoT": "I.O.T.",
            "JSON": "jay-son",
            "YAML": "yam-ul",
            "OAuth": "oh-auth",
            "HTML": "H.T.M.L.",
            "CSS": "C.S.S.",
            "AWS": "A.W.S.",
            "GCP": "G.C.P.",
            "VM": "V.M.",
            "VMs": "V.M.s",
            "PR": "P.R.",

            # =============================================================
            # Benchmark names that sound weird read literally
            # =============================================================
            "GSM8K": "G.S.M. eight K.",
            "GSM8k": "G.S.M. eight K.",
            "MMLU": "M.M.L.U.",
            "HumanEval": "Human Eval",
            "HellaSwag": "Hella-Swag",
            "ARC-C": "arc see",
            "MATH": "math",
            "GPQA": "G.P.Q.A.",

            # =============================================================
            # Beginner-show-specific terms the host uses often
            # =============================================================
            "TTS": "T.T.S.",
            "OCR": "O.C.R.",
            "GAN": "gan",
            "GANs": "gans",
            "VAE": "V.A.E.",
            "CNN": "C.N.N.",
            "RNN": "R.N.N.",
            "BERT": "bert",
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
