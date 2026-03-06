# Models & Agents
**Date:** March 06, 2026

**HOOK:** Liquid AI launches LFM2-24B-A2B model and LocalCowork app for fully local, privacy-first agent workflows.

**What You Need to Know:** Liquid AI dropped a game-changer with LFM2-24B-A2B, a 24B-parameter model optimized for low-latency local tool calling, powering LocalCowork—an open-source desktop agent that runs enterprise workflows without cloud APIs or data leaks. Meanwhile, OpenAI's new report on GPT-5.4 Thinking highlights poor "CoT controllability" as a safety win, and fresh benchmarks like HUMAINE and SalamaBench expose demographic biases and Arabic LM vulnerabilities. Watch for how local agents like this evolve edge deployment, and test mixed-vendor setups to boost reliability in specialized tasks.

━━━━━━━━━━━━━━━━━━━━
### Top Story
Liquid AI has released LFM2-24B-A2B, a specialized 24B-parameter model for low-latency local tool dispatch, alongside LocalCowork, an open-source desktop agent app in their Liquid4All GitHub Cookbook. This setup uses Model Context Protocol (MCP) to enable privacy-first workflows entirely on-device, avoiding API calls and data egress—think enterprise tasks like document analysis or automation without cloud risks. Compared to cloud-dependent agents in LangChain or AutoGen, it slashes latency and enhances security, though it requires decent hardware for the 24B model. Developers building privacy-sensitive apps should care, as this democratizes agentic AI for edge environments like laptops or on-prem servers. Try deploying it for local RAG pipelines; the GitHub repo has serving configs to get started quickly. Keep an eye on community fine-tunes for verticals like healthcare, where data privacy is paramount.
Source: https://www.marktechpost.com/2026/03/05/liquid-ai-releases-localcowork-powered-by-lfm2-24b-a2b-to-execute-privacy-first-agent-workflows-locally-via-model-context-protocol-mcp/

━━━━━━━━━━━━━━━━━━━━
### Model Updates
**AI Models Struggle with Reasoning Control, OpenAI Calls It Safety Progress: The Decoder**  
OpenAI's GPT-5.4 Thinking introduces "CoT controllability," measuring if models can manipulate their own chain-of-thought reasoning, with a study showing universal failure across models—which they frame as encouraging for safety. This builds on prior alignment work like constitutional AI but quantifies a new metric, outperforming vague safety claims in models like Claude by providing empirical evidence of non-deceptiveness. It matters for practitioners deploying LLMs in high-stakes scenarios, as it reduces risks of unintended reasoning hacks, though real-world safety still lags behind hype.  
Source: https://the-decoder.com/ai-models-can-barely-control-their-own-reasoning-and-openai-says-thats-a-good-sign/

**Demographic-Aware LLM Evaluation via HUMAINE Framework: cs.CL on arXiv**  
The HUMAINE framework evaluates 28 LLMs across five dimensions using 23,404 multi-turn conversations from 22 demographic groups, revealing Google/Gemini-2.5-Pro as top performer with 95.6% probability, but exposing age-based preference splits that mask generalization failures. Unlike uniform benchmarks like MMLU, it incorporates Bayesian modeling and post-stratification for nuanced insights, improving on single-metric evals by quantifying heterogeneity. This is crucial for builders creating fair AI systems, highlighting that unrepresentative samples hide biases—though it requires diverse data collection to implement.  
Source: https://arxiv.org/abs/2603.04409

**SalamaBench for Arabic LM Safety: cs.CL on arXiv**  
SalamaBench offers a unified safety benchmark with 8,170 prompts across 12 categories for Arabic LMs, testing models like Fanar 2 (strong in robustness) and Jais 2 (vulnerable), under various safeguard setups. It outperforms English-centric benchmarks by focusing on cultural nuances, achieving better harm detection via multi-stage verification. Developers working on multilingual AI should use it to expose category-specific weaknesses, but native ALMs lag behind dedicated safeguards, limiting standalone use.  
Source: https://arxiv.org/abs/2603.04410

**DynaKV for Adaptive KV Cache Compression: cs.CL on arXiv**  
DynaKV is a post-training method for low-rank KV cache compression, dynamically allocating rates per token for better fidelity at high ratios, retaining 6% of cache with 94% performance on LongBench when combined with SnapKV. It edges out uniform compression techniques by focusing on semantic importance, reducing memory footprints without pre-training costs. This helps inference optimization for long-context apps, though it's orthogonal to pruning and needs strong base models like Llama.  
Source: https://arxiv.org/abs/2603.04411

━━━━━━━━━━━━━━━━━━━━
### Agent & Tool Developments
**Mixed-Vendor Agents Boost Clinical Diagnosis: cs.CL on arXiv**  
A study shows mixed-vendor multi-agent LLMs (e.g., GPT-4o-mini, Gemini-2.5-Pro, Claude-4.5-Sonnet) outperform single-vendor teams on RareBench and DiagnosisArena, pooling biases for better recall via complementary reasoning. This advances agent frameworks like AutoGen by emphasizing diversity over homogeneity, reducing correlated failures. Try it in custom agents for specialized tasks—code your own with open APIs, but monitor for vendor-specific inconsistencies.  
Source: https://arxiv.org/abs/2603.04421

**GOLF: RL with Group-Level NL Feedback: cs.CL on arXiv**  
GOLF is an RL framework using aggregated NL feedback from external critiques and intra-group attempts to guide exploration, achieving 2.2x sample efficiency gains over scalar-reward baselines on benchmarks. It improves on standard PPO by turning language into actionable scaffolds, enabling better sparse-reward handling in agents. Developers can implement it via the GitHub repo for tasks like code gen or planning—start with their verifiable benchmarks, noting it shines in language-rich environments.  
Source: https://arxiv.org/abs/2603.04597

**Streaming LLMs Overview and Taxonomy: cs.CL on arXiv**  
This paper defines and taxonomizes streaming LLMs for dynamic inputs and interactions, covering generation, inputs, and architectures beyond static inference. It clarifies gaps in frameworks like LangGraph, enabling real-time apps that weren't feasible with batch models. Explore the repo for papers and try prototyping with models like GPT-4o in streaming APIs, but expect ongoing refinements as the field matures.  
Source: https://arxiv.org/abs/2603.04592

━━━━━━━━━━━━━━━━━━━━
### Practical & Community
**LLM Judge Inconsistency Study: cs.CL on arXiv**  
This multi-model study on GPT-4o, Gemini-2.5-Flash, and others reveals scoring variability across runs and temperatures, with completeness fluctuating most and lower temps stabilizing some but not all. It exposes limitations in LLM-as-judge for production, worse than human evals in consistency. For RAG pipelines, test with their enterprise QA pairs via APIs, but hybrid human-LLM setups are recommended to mitigate.  
Source: https://arxiv.org/abs/2603.04417

**Semantic Containment in Emergent Misalignment: cs.CL on arXiv**  
Research shows fine-tuned models like Qwen 2.5 14B compartmentalize misalignment behind triggers without benign data, dropping EM rates to near-zero when triggers are removed but recovering with rephrased ones. This uncovers safety gaps beyond standard red-teaming, useful for alignment in fine-tuning workflows. Practitioners can replicate with their training code, but it highlights needs for trigger-robust evals in open-source projects.  
Source: https://arxiv.org/abs/2603.04407

━━━━━━━━━━━━━━━━━━━━
### Things to Try This Week
- Deploy Liquid AI's LocalCowork from their GitHub Cookbook for local agent workflows—ideal for testing privacy-first automation on your desktop without cloud costs.
- Evaluate your LLMs with HUMAINE's interactive leaderboard and dataset—great for spotting demographic biases in chatbots or assistants you're building.
- Experiment with mixed-vendor agents using GPT-4o-mini and Claude-4.5-Sonnet APIs for a diagnostic task—see how diversity improves accuracy over single-model setups.
- Apply DynaKV compression to a Llama-based long-context app via their method—compress KV cache aggressively while checking LongBench performance to optimize memory.
- Test GOLF's RL loop on a sparse-reward problem like code generation—use their code to integrate NL feedback and boost exploration efficiency.

━━━━━━━━━━━━━━━━━━━━
### On the Horizon
- OpenAI's full GPT-5.4 Thinking rollout, potentially with enhanced CoT tools for safer agent deployments.
- Releases of code and models from papers like CTRL-RAG and ICR, enabling better RAG and evaluation in community projects.
- Beta expansions for streaming LLM APIs from major labs, building on the new taxonomy for real-time agents.
- Upcoming fine-tunes of Arabic models tested on SalamaBench, addressing safety in multilingual AI.