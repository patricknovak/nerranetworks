**HOOK:** Aaron Levie declares the enterprise AI shift from chatbots to agents is now underway, moving beyond the "Chat Era."

**What You Need to Know:** Box CEO Aaron Levie says organizations are rapidly moving from simple chat interfaces to autonomous agents that execute real workflows. Today also brings a wave of new technical releases including LG AI Research’s first open-weight vision-language model, MiniMax’s CLI giving agents native multimodal tooling, and an open-source identity platform designed specifically for autonomous agents. The research community dropped a dozen new arXiv papers probing everything from diffusion-model safety to medical reasoning benchmarks, signaling intense activity at the architecture and evaluation layers.

━━━━━━━━━━━━━━━━━━━━
### Top Story
**Aaron Levie Says Enterprise AI Is Shifting From Chatbots To Agents, Warns 'We're Moving From Chat Era...' - Benzinga**
Box CEO Aaron Levie stated that enterprise AI is transitioning from chatbot-style interfaces to full agents capable of executing complex, multi-step work. He argues the “Chat Era” is ending because organizations now demand systems that can act autonomously inside business processes rather than merely answer questions. This matches the surge in agent tooling and frameworks we’re seeing across both startups and big tech. Practitioners building internal tools should start experimenting with agentic patterns now—especially those that combine planning, tool use, and memory—before their competitors treat agents as table stakes. The next 12–18 months will likely separate companies that merely have a chatbot from those running fleets of specialized agents.
Source: https://news.google.com/rss/articles/CBMi5gFBVV95cUxQY1BkNzlMbEdkN21sUzZzTEJoX2JlMkR5aU5ZLXMxdDdxalIwQ0RLSkxYY09wMjFXcy1lRlZ6RXlOS0R0NDl5YkJ1MW1aZ0xoTkQ3aXhUcENSbGF5ZXJWZzJ5V1U5aFJPNHplVlU4QzU1R2hEemV0dE11c2wyT0VWbm1Vc0ZBT3N2VVMtN0dobDJkMmNzTEZHMnJXZF9HLUdRWlQtWUg4ZnU2RXJSZFlmQ2dQSVVPNHpfY1lGdnNjNkI2XzREclJjcUlDZFFlN01JcEZkNkhkTWFvemo5dFFhbDkxbVA5UQ?oc=5

━━━━━━━━━━━━━━━━━━━━
### Model Updates
**EXAONE 4.5 Technical Report**
LG AI Research released EXAONE 4.5, its first open-weight vision-language model built by adding a dedicated visual encoder to the EXAONE 4.0 text backbone. The model was trained with heavy emphasis on curated document-centric corpora, delivering strong gains in document understanding and Korean contextual reasoning while extending context to 256K tokens. It competes well on general benchmarks and outperforms same-scale models on document tasks. Enterprises working with PDFs, forms, or Korean-language content should evaluate it immediately.
Source: https://arxiv.org/abs/2604.08644

**Gemma 4 has a systemic attention failure. Here's the proof.**
An independent researcher using a custom tensor-distribution diagnostic found that Gemma 4 26B (A4B, Q8_0 quant) exhibits severe KL-divergence drift in 21 of 29 affected tensors, almost all belonging to attention layers (attn_k, attn_q, attn_v). In contrast, Qwen 3.5 35B A3B showed healthy attention distributions with only a single broken layer. The analysis suggests Gemma 4 shipped with a systemic architectural or training flaw that standard benchmarks missed. Anyone running Gemma 4 in production should test against this diagnostic before trusting outputs on long or complex sequences.
Source: https://www.reddit.com/r/LocalLLaMA/comments/1sk2s46/gemma_4_has_a_systemic_attention_failure_heres/

**Medical Reasoning with Large Language Models: A Survey and MR-Bench**
A new survey formalizes medical reasoning as iterative abduction-deduction-induction cycles and evaluates training-based and training-free methods under unified conditions. The authors introduce MR-Bench, built from real hospital data, revealing a large gap between exam-style performance and genuine clinical decision accuracy. The work gives practitioners a clearer map of current limitations and a harder benchmark for future medical LLMs.
Source: https://arxiv.org/abs/2604.08559

━━━━━━━━━━━━━━━━━━━━
### Agent & Tool Developments
**ZeroID: Open-source identity platform for autonomous AI agents - Help Net Security**
ZeroID is a new open-source identity and authentication platform built specifically for autonomous AI agents operating across untrusted environments. It addresses core needs around verifiable identity, authorization, and auditability that generic auth systems ignore when the principal is software rather than a human. Developers building multi-agent systems or agents that cross organizational boundaries can integrate it today to reduce spoofing and permission-creep risks.
Source: https://news.google.com/rss/articles/CBMiowFBVV95cUxNQ0tqVkFiZV9IbjR1R1ZMVVZVdHpMZjcta0VTV3hxSllhNkpmaUFWYzdSZmFZQjd3SlZ5UzNlU083Ql9pa0E1ajF4alBYRktpdEVFYnFlTVprNHBQTXNwWWFFNVFhVVdlVmRKdkNHVjdCTFFFSnIwSmgzdDdMOTJKTThjbURYOU9LOUFTcGotQ1NqVmhraFA2OGswMGhxQWlfamZv?oc=5

**MiniMax Releases MMX-CLI: A Command-Line Interface That Gives AI Agents Native Access to Image, Video, Speech, Music, Vision, and Search**
MiniMax open-sourced MMX-CLI, a Node.js command-line tool that exposes its full omni-modal stack (image, video, speech, music, vision, search) to both human developers and AI agents running inside Cursor, Claude Code, or OpenCode. Agents can now call these capabilities natively without custom wrappers. If you are building agents that need to generate or analyze multimodal content, this is one of the cleanest ways to give them those superpowers today.
Source: https://www.marktechpost.com/2026/04/12/minimax-releases-mmx-cli-a-command-line-interface-that-gives-ai-agents-native-access-to-image-video-speech-music-vision-and-search/

**Aethir Claw Enables AI Agents to Execute Creative Workflows - Cryptonews.net**
Aethir Claw is a new execution environment that lets AI agents run creative production workflows (design, video, music, copy) at scale with decentralized compute. It removes many of the orchestration and resource-allocation headaches that previously limited agent creativity. Teams experimenting with generative creative pipelines should test it for cost-effective parallel execution.
Source: https://news.google.com/rss/articles/CBMiXEFVX3lxTE54cDh5SzA3cXU4NXBrQzFtWkRseUxNT1hXbTU0aklTUkZaaE5xckg5Xzg3eHVBbk96OHFNYUFMWXNrcml0LVd1ZjV6NmRUM09LUnpIbGZ1NW54TzB0?oc=5

━━━━━━━━━━━━━━━━━━━━
### Practical & Community
**Llamacpp on chromebook 4 gb ram**
A developer successfully compiled and ran llama.cpp on a 4 GB RAM Chromebook, achieving 3–4 tokens/sec with Qwen 3.5 0.8B 4-bit. The post proves that extremely low-resource devices can still run capable small models locally. If you’re looking for on-device prototyping or want to validate edge deployment targets, this is an encouraging data point and recipe worth replicating.
Source: https://www.reddit.com/r/LocalLLaMA/comments/1sk0fdn/llamacpp_on_chromebook_4_gb_ram/

**Decomposing the Delta: What Do Models Actually Learn from Preference Pairs?**
New research dissects preference optimization (DPO/KTO) by separating generator-level delta (capability gap between chosen/rejected trace producers) from sample-level delta (quality difference within a pair). Larger generator deltas steadily improve out-of-domain reasoning; filtering by sample-level delta yields more data-efficient training. The paper supplies a practical recipe: maximize generator delta when creating pairs and use LLM-as-a-judge filtering to pick the highest-signal examples.
Source: https://arxiv.org/abs/2604.08723

━━━━━━━━━━━━━━━━━━━━
### Under the Hood: Diffusion Language Model Safety
Everyone talks about diffusion LLMs (dLLMs) as though safety is baked into the denoising schedule the same way alignment is baked into RLHF. In practice, their safety alignment rests on one extremely fragile architectural assumption: that the denoising process is strictly monotonic and that once a token is committed it is never revisited.

The core mechanism works like this. A dLLM starts with a fully masked sequence and iteratively unmasks or refines tokens over a fixed number of steps (commonly 64). Safety-tuned versions are trained so that harmful prompts trigger refusal tokens (e.g., “I cannot assist…”) within the first 8–16 steps. Because the schedule treats those early commitments as permanent, the model never reconsiders them. Researchers showed that simply re-masking the refusal tokens and injecting a short affirmative prefix is enough to break safety in two trivial steps—no gradients, no search—achieving 76–82 % attack success rate on HarmBench against current dLLM instruct models.

This exploit is structural, not adversarial sophistication. Adding gradient-based perturbations actually *reduced* attack success, proving the vulnerability lives in the irreversible-commitment schedule itself. The paper’s suggested defenses—safety-aware unmasking orders, step-conditional prefix detectors, and post-commitment re-verification—illustrate that real robustness will require changing the denoising dynamics rather than just training harder.

Practical engineering guidance: treat current dLLM safety as “good enough for non-adversarial use” but never rely on it for high-stakes deployments. If you are building with diffusion-based generators, budget time to implement at least one of the proposed schedule-hardening techniques or keep a separate verifier model in the loop. The gap between perceived safety and actual architectural shallowness is currently one of the widest in the entire LLM stack.

━━━━━━━━━━━━━━━━━━━━
### Things to Try This Week
- Try **MMX-CLI** inside Cursor or Claude Code to give your agents native image, video, speech, and search tools—far simpler than stitching separate APIs.
- Evaluate **EXAONE 4.5** on your document-heavy workflows; the targeted training on enterprise docs makes it worth benchmarking against Claude-3.5 or GPT-4o for PDF understanding.
- Run the Gemma 4 tensor-diagnostic pastebin script against any 26B-class model you depend on—catches attention collapse that standard benchmarks miss.
- Experiment with **ZeroID** if you are designing multi-agent systems that cross trust boundaries; adding proper agent identity early prevents painful refactoring later.
- Use the generator-level vs sample-level delta framework from the new preference optimization paper to curate your next DPO dataset—filtering by judged quality can dramatically improve data efficiency.

━━━━━━━━━━━━━━━━━━━━
### On the Horizon
- More vision-language models emphasizing document and long-context understanding are expected from additional labs following LG’s lead.
- Agent identity and authorization standards will likely consolidate around projects like ZeroID as fleets of autonomous agents become commonplace.
- Expect rapid follow-up work on diffusion LLM defenses now that the re-masking vulnerability is public.
- Medical-reasoning benchmarks such as MR-Bench should drive more clinically grounded evaluations instead of exam-style leaderboards in the coming months.