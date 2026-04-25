**HOOK:** Google DeepMind's Vision Banana shows image generation pretraining may be the true foundation model path for computer vision, beating SAM 3 on segmentation and Depth Anything V3 on metric depth.

**What You Need to Know:** DeepMind argues convincingly that generative pretraining for images delivers the same leap for vision that GPT-style pretraining delivered for language, with strong benchmark results to back it. Meanwhile, Qwen3.6-35B-A3B continues to impress the local LLM community with agentic coding performance that rivals much larger cloud models, and new prompting guidance for GPT-5.5 emphasizes treating it as an entirely new model family rather than a drop-in upgrade. This week pay attention to the accelerating quality of sparse and MoE local models alongside fresh guidance on how to actually extract performance from the latest frontier releases.

━━━━━━━━━━━━━━━━━━━━
### Top Story
Google DeepMind has introduced Vision Banana, an instruction-tuned image generator whose pretraining approach it positions as the vision equivalent of GPT-style language pretraining. The model reportedly outperforms SAM 3 on segmentation tasks and Depth Anything V3 on metric depth estimation, suggesting that scaling generative objectives on images yields more transferable representations than traditional supervised vision pipelines. This matters because it reframes computer vision foundation models around generation rather than pure discriminative training, potentially unifying image understanding and creation under one pretraining paradigm. Developers working on segmentation, depth, or multimodal agents can now experiment with a single generative backbone that appears stronger on core geometric tasks than specialized models. Watch for follow-up releases that integrate this into agentic vision workflows or open-weight variants that let the community stress-test the claims at scale.  
Source: https://www.marktechpost.com/2026/04/25/google-deepmind-introduces-vision-banana-an-instruction-tuned-image-generator-that-beats-sam-3-on-segmentation-and-depth-anything-v3-on-metric-depth-estimation/

━━━━━━━━━━━━━━━━━━━━
### Model Updates
**Qwen3.6-35B-A3B-UD-IQ4_XS shows surprising real-world coding strength: r/LocalLLaMA**  
A community tester successfully used the sparse Qwen3.6-35B-A3B model to port a non-trivial C++ audio synthesis library (OddVoices) to Rust in roughly five hours across two nights, producing output that sounds virtually identical to the original despite minor speed and edge-case bugs. The model demonstrated strong self-correction, referencing the source implementation when directed and updating its own code accordingly — behavior previously associated with much larger cloud models. Users report it outperforms Gemma 4 on agentic coding tasks while running several times faster due to sparsity. This continues the trend of highly capable local MoE models that close the gap with proprietary APIs for software engineering workloads.  
Source: https://www.reddit.com/r/LocalLLaMA/comments/1sv3ff6/qwen3635ba3budiq4_xs_c_to_rust_code_port_test_it/

**DeepSeek V4 Pro (1.6T-A49B) and Flash (284B-A13B) now runnable on Huawei Ascend: Latent.Space**  
DeepSeek has released both base and instruct versions of its newest MoE models, optimized to run on Huawei Ascend hardware. While no longer the outright benchmark leader, the release underscores DeepSeek’s continued commitment to open weights, base models, and detailed research papers at a time when many labs are retreating from full openness. The models target practical inference on non-NVIDIA silicon, expanding accessible high-parameter MoE options. Practitioners running on Ascend clusters or seeking alternatives to closed ecosystems should evaluate the instruct variants for coding and reasoning tasks.  
Source: https://www.latent.space/p/ainews-deepseek-v4-pro-16t-a49b-and

**Qwen3.6-27B KV cache quantization results defy common wisdom: r/LocalLLaMA**  
Perplexity testing on Qwen3.6-27B-Q5_K_M at 200k context showed remarkably small degradation: Q4_0 added only +0.0148 PPL versus F16 baseline, while Turbo3 (3-bit) added +0.0888 — still considered safe for many programming workloads. The model’s density above 20B parameters appears to make it unusually robust to aggressive KV cache compression. Note that some commenters caution PPL alone can understate downstream impact on math-heavy benchmarks like AIME. If you run dense 27B-class models on limited VRAM, Q4 or Turbo3 KV cache is now worth testing aggressively.  
Source: https://www.reddit.com/r/LocalLLaMA/comments/1suur3s/qwen36_27bs_surprising_kv_cache_quantization_test/

**GPT-5.5 prompting guide emphasizes fresh baselines: Simon Willison's Weblog**  
OpenAI released detailed guidance alongside GPT-5.5 API availability, recommending developers treat it as a new model family and start prompt tuning from the smallest viable prompt rather than porting legacy stacks. A practical tip for long-running agentic tasks: emit a short user-visible progress message before tool calls to improve perceived responsiveness. The guide also includes migration advice for codebases via their Codex agent.  
Source: https://simonwillison.net/2026/Apr/25/gpt-5-5-prompting-guide/#atom-everything

━━━━━━━━━━━━━━━━━━━━
### Agent & Tool Developments
**GitNexus gives Claude Code and Cursor full structural codebase awareness: MarkTechPost**  
Abhigyan Patwari’s open-source MCP-native knowledge graph engine, now with over 19k GitHub stars, addresses a core failure mode of coding agents: editing code they don’t truly understand. By building a live structural graph of the repository, GitNexus supplies agents with explicit awareness of dependencies, call graphs, and architectural intent. Both Claude Code and Cursor users can integrate it today to reduce hallucinated refactors and improve large-scale changes.  
Source: https://www.marktechpost.com/2026/04/24/meet-gitnexus-an-open-source-mcp-native-knowledge-graph-engine-that-gives-claude-code-and-cursor-full-codebase-structural-awareness/

**Open-source multi-cursor/background computer-use agent using Hermes + Qwen3.6-35B + Cua-Driver: r/LocalLLaMA**  
A new fully local implementation combines Hermes Agent, the recently praised Qwen3.6-35B-A3B-4bit model, and Cua-Driver to deliver Codex-like multi-cursor and background computer control without cloud dependencies. The project demonstrates that current open models plus lightweight drivers can already approximate frontier agentic computer-use capabilities. Builders experimenting with local agents should examine the stack for self-hosted automation or coding workflows.  
Source: https://www.reddit.com/r/LocalLLaMA/comments/1suux6h/open_source_multicursorbackground_computeruse/

━━━━━━━━━━━━━━━━━━━━
### Practical & Community
**Open-source 9-task benchmark for coding-agent retrieval augmentation: r/MachineLearning**  
The paper-lantern-challenges repo provides fully reproducible prompts, agent code paths, and evaluation scripts across nine practical software tasks (test generation, text-to-SQL, PDF/contract extraction, PR review, classification, routing, summarization, etc.). Adding a retrieval tool over recent CS literature produced deltas from +0.010 to +0.320, with the largest gains on extraction and test-generation tasks that benefited from 2025–2026 techniques unknown to the base models. Every prediction file and approach.md is public, making it an excellent test harness for anyone building RAG-enhanced coding agents.  
Source: https://www.reddit.com/r/MachineLearning/comments/1suzqxe/opensource_9task_benchmark_for_codingagent/

**Microsoft OpenMementos tutorial covers trace structure, context compression, and fine-tuning prep: MarkTechPost**  
A Colab-ready walkthrough shows how to stream the OpenMementos dataset, parse its block/memento token format, measure compression ratios across domains, and prepare reasoning traces for fine-tuning. The memento representation offers substantial context compression while preserving structured reasoning summaries. Fine-tuning practitioners working on long-horizon agent memory or chain-of-thought distillation should run the notebook to understand the format before building their own datasets.  
Source: https://www.marktechpost.com/2026/04/24/a-coding-implementation-on-microsofts-openmementos-with-trace-structure-analysis-context-compression-and-fine-tuning-data-preparation/

**llm 0.31 adds GPT-5.5 support and verbosity/image-detail controls: Simon Willison's Weblog**  
The latest release of Simon Willison’s popular CLI tool adds direct support for the new GPT-5.5 model, a `-o verbosity low|medium|high` option for GPT-5+ models, and `-o image_detail` controls (low/high/auto/original). Extra OpenAI models defined in YAML are now also registered for async use. If you already use `llm` for local experimentation or rapid prototyping, upgrading gives immediate access to the latest OpenAI capabilities with finer output control.  
Source: https://simonwillison.net/2026/Apr/24/llm/#atom-everything

━━━━━━━━━━━━━━━━━━━━
### Under the Hood: Mixture-of-Experts Routing at Scale
Everyone talks about MoE as if the router is a magical “pick the best expert” black box that simply works once you have enough parameters. In practice, router training is a delicate optimization dance full of load-balancing tricks, auxiliary losses, and careful initialization that determine whether the model actually uses its capacity or collapses into a few dominant experts.

The core insight is that the router is itself a tiny neural network trained jointly with the rest of the model using a combination of the main loss and an auxiliary load-balancing loss. Without the auxiliary term, routers tend to converge on a handful of experts, leaving the majority under-utilized; the auxiliary loss penalizes uneven token-to-expert assignment across a batch, typically measured by coefficient of variation of expert load. Modern implementations further add noise or stochastic routing during training, then switch to deterministic top-k during inference.

At the scale of DeepSeek-V4’s 1.6T total parameters with 49B activated, the engineering reality is that expert parallelism, all-to-all communication patterns, and careful placement of experts across accelerators dominate runtime cost. The “heavily compressed attention” mentioned in recent releases is often a direct response to the memory wall created by storing full key/value states for a million-token context across dozens of experts; techniques like compressed sparse attention trade exact attention for approximate retrieval plus heavy quantization to keep activation memory manageable.

These tradeoffs are not free. Adding stronger load-balancing can slightly hurt final loss because it forces the model to use “suboptimal” experts on some tokens, while aggressive compression of the attention states can degrade needle-in-haystack retrieval once context exceeds a few hundred thousand tokens. The quality gain from MoE tends to be largest in the 30–200B active parameter regime; beyond that the returns diminish and communication overhead can dominate.

The practical engineering guidance is straightforward: when choosing between a dense model and an MoE of similar activated size, prefer MoE if your workload has high variance in token difficulty (coding, math, multilingual) and you have the infrastructure to handle all-to-all traffic. The gotcha that bites most teams is treating the router as an afterthought during fine-tuning — without re-tuning the auxiliary loss and possibly re-introducing noise, the specialization learned in pretraining collapses and you lose the speed/quality advantage you paid for.

━━━━━━━━━━━━━━━━━━━━
### Things to Try This Week
- Try Qwen3.6-35B-A3B (Q4 or Q5 quant) inside Cline + VSCodium for local agentic coding — the self-correction and codebase exploration quality is reportedly closer to recent cloud models than previous local attempts.
- Integrate GitNexus into your Claude Code or Cursor workflow if you routinely see agents edit files without understanding surrounding architecture — the 19k-star knowledge graph gives immediate structural awareness.
- Run the paper-lantern-challenges benchmark suite against your own RAG coding agent to quantify exactly how much retrieval over recent literature improves extraction, test generation, and review tasks.
- Upgrade to llm 0.31 and test the new verbosity and image-detail controls with GPT-5.5 — the guidance to start prompt tuning from a fresh minimal baseline is worth following before porting old stacks.
- Experiment with Turbo3 or Q4 KV cache on Qwen3.6-27B at 128k–200k context if you’re VRAM constrained — the perplexity numbers suggest you may be able to run larger effective context than common wisdom allows.

━━━━━━━━━━━━━━━━━━━━
### On the Horizon
- Nous Research AMA on Wednesday (April 29) focusing on Hermes Agent — expect deeper discussion on open-source agent orchestration and memory techniques.
- Continued releases in the DeepSeek V4 family, including potential smaller variants or further Ascend-specific optimizations.
- Growing ecosystem around MCP-native tools as more coding environments adopt structured knowledge graphs and context protocols.
- Further guidance and fine-tuning recipes for GPT-5.5 as developers migrate production agents and discover which prompting patterns no longer transfer from earlier GPT-5.x models.