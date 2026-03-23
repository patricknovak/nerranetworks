**HOOK:** TrustFlow introduces topic-aware vector reputation for multi-agent systems, replacing scalar scores with queryable multi-dimensional vectors.

**What You Need to Know:** Today’s arXiv drop is dominated by multi-agent research, with new frameworks for reputation propagation, co-evolutionary prompt optimization, group-based communication topologies, and long-horizon agent training. The most immediately practical releases are Helix for joint question-prompt optimization and GoAgent for explicit group-aware topologies. Developers building agent ecosystems should pay attention to TrustFlow’s resistance to common attacks and the substantial gains shown in long-horizon web tasks.

━━━━━━━━━━━━━━━━━━━━
### Top Story
TrustFlow introduces a reputation propagation algorithm that assigns each software agent a multi-dimensional reputation vector rather than a scalar score. Reputation propagates through an interaction graph using topic-gated transfer operators modulated by content embeddings, with convergence guaranteed by the contraction mapping theorem via a family of Lipschitz-1 operators and composable information-theoretic gates. It achieves up to 98% multi-label Precision@5 on dense graphs and 78% on sparse ones, while resisting sybil attacks, reputation laundering, and vote rings with at most a 4 percentage-point precision drop on a 50-agent, 8-domain benchmark. Unlike PageRank or Topic-Sensitive PageRank, TrustFlow produces vector reputations directly queryable by dot product in the same embedding space as user queries. This enables more nuanced trust decisions in production multi-agent ecosystems. The work provides a solid foundation for reputation systems that actually understand topical expertise.

Source: https://arxiv.org/abs/2603.19452

━━━━━━━━━━━━━━━━━━━━
### Model Updates
**Helix: Dual-Helix Co-Evolutionary Multi-Agent System for Prompt Optimization**  
Helix jointly optimizes question reformulation and prompt instructions through a three-stage co-evolutionary framework with planner-guided decomposition, dual-track agent critique, and strategy-driven question generation. It delivers up to 3.95% performance improvements across 12 benchmarks against 6 strong baselines while maintaining favorable optimization efficiency. This directly addresses the limitation of existing automated prompt optimization methods that treat user questions as immutable. Developers working on agent reliability should test Helix when prompt quality and query clarity are interdependent.

Source: https://arxiv.org/abs/2603.19732

**A Subgoal-driven Framework for Improving Long-Horizon LLM Agents**  
The framework combines inference-time subgoal decomposition using proprietary models with MiRA, a milestone-based RL training method that supplies dense rewards. It lifts Gemini by ~10% absolute success rate on WebArena-Lite and boosts open-source Gemma3-12B from 6.4% to 43.0% success rate, surpassing GPT-4-Turbo (17.6%), GPT-4o (13.9%), and prior open SOTA WebRL (38.4%). This is one of the clearest demonstrations yet that explicit planning plus milestone rewards can close the long-horizon gap. Teams building browser or OS agents should evaluate the MiRA approach.

Source: https://arxiv.org/abs/2603.19685

**Is Your LLM-as-a-Recommender Agent Trustable?**  
Introduces BiasRecBench across paper review, e-commerce, and job recruitment domains, revealing that even SOTA models (Gemini-2.5/3-pro, GPT-4o, DeepSeek-R1) frequently succumb to injected contextual biases despite being able to identify ground truth. The benchmark uses a calibrated quality-margin synthesis pipeline to surface these vulnerabilities. This exposes a critical reliability bottleneck for high-stakes agentic recommendation workflows and underscores the need for specialized alignment in recommender agents.

Source: https://arxiv.org/abs/2603.17417

━━━━━━━━━━━━━━━━━━━━
### Agent & Tool Developments
**GoAgent: Group-of-Agents Communication Topology Generation**  
GoAgent treats collaborative groups as atomic units, using an LLM to enumerate task-relevant candidate groups then autoregressively selecting and connecting them, augmented by a conditional information bottleneck to compress inter-group communication. It reaches 93.84% average accuracy across six benchmarks while reducing token consumption by ~17%. This explicit group modeling outperforms node-centric topology methods that let structure emerge implicitly. Teams building complex multi-agent systems should experiment with the group-centric approach.

Source: https://arxiv.org/abs/2603.19677

**ClawWorm: Self-Propagating Attacks Across LLM Agent Ecosystems**  
Researchers demonstrated the first self-replicating worm against the OpenClaw platform (40k+ active instances), achieving persistent configuration hijacking, payload execution on reboot, and multi-hop propagation from a single message. The attack achieved 64.5% success rate across 1,800 trials on four LLM backends. The work includes responsible disclosure elements and analyzes architectural root causes at each trust boundary. This highlights that execution-level filtering is insufficient when skill supply chains remain vulnerable.

Source: https://arxiv.org/abs/2603.15727

━━━━━━━━━━━━━━━━━━━━
### Practical & Community
**GT-Space: Heterogeneous Collaborative Perception with Ground Truth Feature Space**  
GT-Space creates a common feature space from ground-truth labels so heterogeneous agents (different sensors or architectures) only need a single adapter module instead of pairwise interpreters. A contrastive-loss fusion network handles diverse modality combinations. It outperforms baselines on OPV2V, V2XSet, and real-world RCooper datasets. Code is promised at https://github.com/KingScar/GT-Space. Autonomous driving and robotics teams facing heterogeneous fleets should watch for the release.

Source: https://arxiv.org/abs/2603.19308

**IndoorR2X: Indoor Robot-to-Everything Coordination with LLM-Driven Planning**  
The benchmark and simulation framework integrates mobile robots with existing indoor IoT sensors to build a global semantic state, reducing redundant exploration. It enables LLM-based high-level coordination and provides configurable environments for evaluating semantic collaboration strategies. Experiments show IoT-augmented modeling improves efficiency and reliability. Practitioners building indoor multi-robot systems now have a standardized way to test R2X approaches.

Source: https://arxiv.org/abs/2603.20182

━━━━━━━━━━━━━━━━━━━━
### Under the Hood: Reputation Vectors vs Scalar Trust
Everyone talks about “trust” in multi-agent systems as if it’s a single number you can PageRank. In practice, scalar reputation collapses critical context and makes topical expertise impossible to query directly. TrustFlow replaces the scalar with a vector in the same embedding space as user queries, so reputation becomes a dot-product lookup—elegant and computationally cheap at inference time. The key engineering insight is topic-gated transfer operators that modulate each graph edge by the content embedding of the interaction; these operators are carefully designed to be Lipschitz-1, guaranteeing convergence via the contraction mapping theorem regardless of graph density. The composable information-theoretic gates further prevent reputation laundering by controlling information flow per topic. On sparse graphs the method still reaches 78% Precision@5, showing the vector approach scales where scalar methods degrade. The gotcha that bites most teams is assuming uniform propagation works across domains—once you have more than 3–4 distinct topics, scalar methods lose too much signal. Use vector reputation when your agents must demonstrate different expertise per query; stick with scalar only for very narrow, single-domain swarms.

━━━━━━━━━━━━━━━━━━━━
### Things to Try This Week
- Try the MiRA milestone-based RL approach on your long-horizon web or browser agents — the jump from 6.4% to 43% on Gemma3-12B is too large to ignore.
- Experiment with GoAgent’s group-centric topology generation if you’re coordinating more than 5 agents on complex tasks — the 17% token reduction is immediately valuable.
- Test your current LLM-as-recommender pipeline against simple contextual biases using the BiasRecBench methodology — you may be surprised how easily high-stakes recommendations are hacked.
- Explore TrustFlow-style vector reputation for any multi-agent system where topical trust matters — the dot-product queryability makes it practical to integrate today.
- Download the upcoming GT-Space code when released and evaluate it against your heterogeneous sensor fusion setup.

━━━━━━━━━━━━━━━━━━━━
### On the Horizon
- Expect more agent topology and reputation papers building directly on GoAgent and TrustFlow in the coming weeks.
- Watch for the public release of ClawWorm defense recommendations once responsible disclosure concludes.
- FinReasoning and GeoChallenge benchmarks are likely to spawn improved financial and geometric reasoning models quickly.
- Continued progress on hybrid real-time + asynchronous agent engines (see DuCCAE) will influence production conversational systems.