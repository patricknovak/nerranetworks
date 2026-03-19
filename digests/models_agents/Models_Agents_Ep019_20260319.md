**# Models & Agents**
**Date:** March 19, 2026

**HOOK:** Mamba-3 introduces 2x smaller states and enhanced MIMO decoding, pushing state-space models closer to practical deployment against Transformers.

**What You Need to Know:** Today brings a wave of new agentic research, with Carnegie Mellon and Princeton researchers unveiling Mamba-3 as a promising architecture for inference efficiency, while over a dozen arXiv papers explore everything from emergent trust in agents and governed memory systems to bias vulnerabilities in LLM recommenders. The most immediately useful releases for developers are practical agent memory architectures and new evaluation frameworks that address real production pain points in multi-agent workflows. Pay attention to the surge in agent governance, memory, and reliability research — these are the pieces needed to move from demos to dependable systems.

━━━━━━━━━━━━━━━━━━━━
### Top Story
Mamba-3, a new state space model from researchers at Carnegie Mellon University, Princeton University, and Together, advances the architecture with 2x smaller states and improved MIMO decoding hardware efficiency. While Transformers remain dominant, their quadratic complexity continues to create deployment bottlenecks at scale, making efficient alternatives like Mamba increasingly relevant as inference-time compute becomes a primary performance driver. 

The work focuses on both model quality and inference efficiency, directly targeting the memory and computational limitations that hinder Transformer deployment in production. This matters for anyone running large-scale inference or seeking alternatives to attention-based models.

Developers working on efficient inference pipelines should watch how this evolves, particularly the hardware efficiency gains. The paper provides a fresh look at what’s possible beyond Transformers for real-world deployment.

Source: https://www.marktechpost.com/2026/03/18/meet-mamba-3-a-new-state-space-model-frontier-with-2x-smaller-states-and-enhanced-mimo-decoding-hardware-efficiency/

━━━━━━━━━━━━━━━━━━━━
### Model Updates
**MiroThinker-1.7 & H1: Towards Heavy-Duty Research Agents via Verification — arXiv**
MiroThinker-1.7 adds an agentic mid-training stage focused on structured planning, contextual reasoning, and tool interaction, while MiroThinker-H1 incorporates local and global verification directly into the reasoning process. The models target complex long-horizon tasks across open-web research, scientific reasoning, and financial analysis, with open-source releases of MiroThinker-1.7 and the smaller 1.7-mini variant. This represents meaningful progress toward more reliable multi-step research agents that can audit their own reasoning chains.

Source: https://arxiv.org/abs/2603.15726

**MedArena: Comparing LLMs for Medicine-in-the-Wild Clinician Preferences — arXiv**
MedArena is an interactive evaluation platform where clinicians test and compare LLMs using their own real medical queries, collecting 1571 preferences across 12 models. Results show Gemini 2.0 Flash Thinking, Gemini 2.5 Pro, and GPT-4o leading via Bradley-Terry ratings, with clinicians prioritizing depth, detail, and clarity over pure factual accuracy. Only one-third of questions resembled traditional factual recall benchmarks, highlighting the gap between standard evals and actual clinical utility.

Source: https://arxiv.org/abs/2603.15677

**Recursive Language Models Meet Uncertainty: Self-Reflective Program Search — arXiv**
SRLM augments recursive language models with uncertainty-aware self-reflection using self-consistency, reasoning length, and verbalized confidence signals. It delivers up to 22% improvement over standard RLM under the same time budget and shows that self-reflective program search can match or exceed recursive approaches without needing explicit recursion. The work reveals recursion itself is often not the main driver of performance.

Source: https://arxiv.org/abs/2603.15653

━━━━━━━━━━━━━━━━━━━━
### Agent & Tool Developments
**Governed Memory: A Production Architecture for Multi-Agent Workflows — arXiv**
Governed Memory introduces a shared memory and governance layer addressing memory silos, governance fragmentation, and unstructured memories in enterprise multi-agent systems. It uses a dual memory model (atomic facts + schema-enforced properties), tiered governance routing, reflection-bounded retrieval, and closed-loop schema lifecycle. Already in production at Personize.ai, it achieves 99.6% fact recall, 92% governance routing precision, 50% token reduction, and 74.8% accuracy on the LoCoMo benchmark with no quality penalty from governance.

Source: https://arxiv.org/abs/2603.17787

**TerraLingua: Emergence and Analysis of Open-endedness in LLM Ecologies — arXiv**
TerraLingua creates a persistent multi-agent ecology with resource constraints and limited lifespans, leading to emergent cooperative norms, division of labor, governance attempts, and cumulative cultural processes. An AI Anthropologist agent analyzes behavior, group structure, and artifact evolution. This provides a valuable platform for studying and guiding real-world agentic populations toward socially beneficial outcomes.

Source: https://arxiv.org/abs/2603.16910

**In Trust We Survive: Emergent Trust Learning — arXiv**
Emergent Trust Learning (ETL) is a lightweight, plug-in trust-based control algorithm for existing AI agents that enables cooperation in competitive environments with shared resources. It maintains a compact internal trust state modulating memory, exploration, and action selection using only individual rewards and local observations. Evaluated successfully in grid resource worlds, hierarchical Tower environments, and Iterated Prisoner’s Dilemma.

Source: https://arxiv.org/abs/2603.17564

━━━━━━━━━━━━━━━━━━━━
### Practical & Community
**Is Your LLM-as-a-Recommender Agent Trustable? — arXiv**
BiasRecBench reveals that current LLMs (including Gemini-2.5/3-pro, GPT-4o, DeepSeek-R1) are easily hacked by contextual biases in high-stakes recommendation tasks like paper review, e-commerce, and job recruitment. Despite being able to identify ground truth, agents frequently succumb to injected logical biases. The work calls for specialized alignment strategies for the growing "LLM-as-a-Recommender" paradigm.

Source: https://arxiv.org/abs/2603.17417

**Agentic Cognitive Profiling for Alzheimer's Detection — arXiv**
Agentic Cognitive Profiling (ACP) decomposes cognitive assessments into atomic tasks orchestrated by specialized LLM agents, delegating quantification to deterministic function calling to restore clinical construct validity. Evaluated on 402 participants across eight tasks, it achieves 90.5% score match rate and 85.3% AD prediction accuracy while producing interpretable profiles. Demonstrates that validity and performance need not be traded off.

Source: https://arxiv.org/abs/2603.17392

━━━━━━━━━━━━━━━━━━━━
### Things to Try This Week
- Try Governed Memory concepts in your multi-agent workflows if you're struggling with memory silos or inconsistent agent behavior — the dual memory model and schema enforcement are production-tested
- Test MiroThinker-1.7 or 1.7-mini for research-oriented tasks that require long-horizon reasoning and tool use — the open-source release makes it easy to experiment locally
- Run your current LLM recommender prompts through BiasRecBench-style tests to see how vulnerable your agents are to contextual biases
- Explore TerraLingua-style persistent environments if you're building agent ecologies — resource constraints and lifespans dramatically change emergent behavior
- Compare SRLM-style self-reflective program search against standard RAG or recursive approaches on your long-context tasks

━━━━━━━━━━━━━━━━━━━━
### On the Horizon
- Expect more verification-heavy research agents as MiroThinker-H1's local/global verification approach gains traction
- Continued growth in agent memory governance solutions as production multi-agent systems scale
- More interactive, human-preference-based benchmarks like MedArena across additional domains
- Further hybridization of state-space models with hardware-aware optimizations following Mamba-3

The agent ecosystem is clearly maturing from novel demos toward addressing the hard problems of memory, trust, governance, and reliability. These releases give developers concrete new tools and research directions to build more robust systems today.