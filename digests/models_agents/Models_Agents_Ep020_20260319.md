**HOOK:** Agentic systems with RAG dramatically outperform plain LLMs in fairness auditing for clinical AI, according to new ablation studies.

**What You Need to Know:** Today's arXiv drop is dominated by multi-agent systems and agentic architectures tackling real-world coordination problems. The standout is a two-agent fairness auditing system for early-onset colorectal cancer detection that uses Domain Expert and Fairness Consultant agents, with the RAG-enabled version delivering the highest semantic similarity to expert judgments across 8B, 20B, and 120B Ollama models. Several papers also explore economic frameworks for agent commerce, noncooperative human-AI dynamics using Prospect Theory, and scalable UAV networking via MARL+LLM hybrids.

━━━━━━━━━━━━━━━━━━━━
### Top Story
A new paper evaluates an agentic AI system for fairness auditing in biomedical models, specifically targeting bias in early-onset colorectal cancer (EO-CRC) detection. Researchers implemented a two-agent architecture consisting of a Domain Expert Agent that synthesizes literature on EO-CRC disparities and a Fairness Consultant Agent that recommends sensitive attributes and fairness metrics. An ablation study compared three Ollama LLMs (8B, 20B, and 120B parameters) across pretrained LLM-only, Agent without RAG, and Agent with RAG configurations. The Agent with RAG configuration achieved the highest semantic similarity to expert-derived reference statements, particularly for disparity identification. This suggests that agentic systems enhanced with retrieval can help scale fairness auditing in clinical AI where domain expertise is limited. The work highlights practical pathways for more accountable medical AI deployment.

Source: https://arxiv.org/abs/2603.17179

━━━━━━━━━━━━━━━━━━━━
### Model Updates
**A Family of LLMs Liberated from Static Vocabularies**
Researchers released a family of hierarchical autoregressive transformer (HAT) models, including conversions of Llama 3.1 8B and 70B into byte-level HAT architectures (Llama-3.1-8B-TFree-HAT and Llama-3.1-70B-TFree-HAT) plus a 7B model trained from scratch on nearly 4 trillion words. The HAT design uses an encoder to aggregate bytes into word embeddings for the backbone transformer, improving text compression and robustness to intra-word variations like spelling differences. After pre-training, SFT, and DPO in English and German, the models improve on original Llama 3.1 in most benchmarks while offering better adaptability to new domains.

Source: https://arxiv.org/abs/2603.15953

**Morphemes Without Borders: Evaluating Root-Pattern Morphology in Arabic Tokenizers and LLMs**
A comprehensive study across seven Arabic-centric and multilingual LLMs and their tokenizers found that tokenizer morphological alignment is neither necessary nor sufficient for strong morphological generation performance in Arabic's non-concatenative root-pattern system. The work introduces a new test set for productive root-pattern generation and challenges assumptions about the importance of morphologically-aware tokenization for downstream capabilities.

Source: https://arxiv.org/abs/2603.15773

**MoLoRA: Composable Specialization via Per-Token Adapter Routing**
MoLoRA introduces per-token LoRA routing that enables multiple domain-specific adapters to be loaded simultaneously, with a learned router selecting the appropriate adapter for each token. This overcomes limitations of per-sequence routing in multimodal or mixed-capability scenarios. The approach allows Qwen3-1.7B with MoLoRA to outperform Qwen3-8B across four reasoning benchmarks while being 4.7x smaller, demonstrating that specialization beats scale.

Source: https://arxiv.org/abs/2603.15965

━━━━━━━━━━━━━━━━━━━━
### Agent & Tool Developments
**Capability-Priced Micro-Markets: A Micro-Economic Framework for the Agentic Web over HTTP 402**
This paper presents Capability-Priced Micro-Markets (CPMM), integrating MIT's Project NANDA for capability-based security, HTTP 402 micropayments, and the Agent Capability Negotiation and Binding Protocol. The framework formalizes agent interactions as repeated bilateral games with incomplete information and introduces "privacy elasticity of demand" to quantify information disclosure tradeoffs. It theoretically converges to a constrained Radner equilibrium, providing a foundation for scalable commerce among autonomous agents.

Source: https://arxiv.org/abs/2603.16899

**Communication to Completion: Modeling Collaborative Workflows with Intelligent Multi-Agent Communication**
Researchers introduce the Communication to Completion (C2C) framework that treats communication as a constrained resource with realistic temporal costs, using an Alignment Factor (AF) metric inspired by Shared Mental Models. Tested on 15 software engineering workflows with teams of 5-17 agents, cost-aware strategies achieved over 40% higher efficiency than unconstrained interaction. The work reveals emergent patterns like manager-centric hub-and-spoke topologies and escalation from async to sync channels, consistent across GPT-5.2, Claude Sonnet 4.5, and Gemini 2.5 Pro.

Source: https://arxiv.org/abs/2510.19995

**Scalable UAV Multi-Hop Networking via Multi-Agent Reinforcement Learning with Large Language Models**
MRLMN combines MARL with LLMs using a grouping strategy, reward decomposition, behavioral constraints on key UAVs, and knowledge distillation from LLM agents to MARL agents via Hungarian algorithm matching. The system significantly outperforms MAPPO baselines in coverage and communication quality for disaster response scenarios. This addresses scalability and exploration challenges in large dynamic environments.

Source: https://arxiv.org/abs/2505.08448

━━━━━━━━━━━━━━━━━━━━
### Practical & Community
**Noncooperative Human-AI Agent Dynamics**
A new study models humans with Prospect Theory preferences (reference dependence and loss aversion) while AI agents use standard expected utility, testing them in matrix games and specialized scenarios. The accompanying code repository enables extensive simulations across AI, aware humans, and learning Prospect agents. The work surfaces patterns ranging from near-identical behavior to Prospect Theory anomalies and unexpected surprises in mixed human-AI competition.

Source: https://arxiv.org/abs/2603.16916

**Adaptive Accountability in Networked MAS: Tracing and Mitigating Emergent Norms at Scale**
The Adaptive Accountability Framework (AAF) adds cryptographically verifiable provenance, change point detection, causal influence graphs, and cost-bounded interventions to networked multi-agent systems. In a massive simulation suite (87,480 runs, up to 500 agents), AAF reduced compromise ratio in 96% of regimes while preserving social welfare. It detects violations with median delay of 71 steps and high attribution accuracy even under 10% Byzantine agents.

Source: https://arxiv.org/abs/2512.18561

**FACET: Teacher-Centred LLM-Based Multi-Agent Systems**
FACET is a three-agent system (learner agents simulating cognitive/motivational profiles, a teacher agent adapting content, and an evaluator agent for quality assurance) designed to generate personalized mathematics worksheets. Tested on grade 8 curriculum, it showed high stability and received positive teacher feedback on structure and task suitability. The framework offers a teacher-facing approach to personalization in heterogeneous classrooms.

Source: https://arxiv.org/abs/2508.11401

━━━━━━━━━━━━━━━━━━━━
### Things to Try This Week
- Try the **Ollama-based two-agent fairness auditing system** (Domain Expert + Fairness Consultant with RAG) for your own domain-specific auditing tasks — the ablation shows clear gains over plain LLM prompting.
- Experiment with **MoLoRA's per-token routing** if you're doing multimodal or multi-domain generation — load several specialized LoRAs and let the router handle token-level decisions.
- Test **HAT-based Llama conversions** (Llama-3.1-8B-TFree-HAT) for tasks involving spelling variations or new terminology — the byte-to-word approach offers robustness advantages.
- Explore the **C2C framework concepts** in your multi-agent workflows by adding explicit communication costs and measuring the Alignment Factor — the 40%+ efficiency gains are compelling.
- Check out the **noncooperative human-AI dynamics codebase** if you're modeling mixed human-AI systems — running Prospect Theory humans against expected utility AIs produces fascinating strategic differences.

━━━━━━━━━━━━━━━━━━━━
### On the Horizon
- Continued development of economic infrastructure for agent-to-agent commerce, with HTTP 402 extensions and capability-based security likely seeing more implementations.
- Further integration of LLMs into MARL systems for scalable coordination in robotics and networking applications.
- More sophisticated accountability frameworks for large-scale multi-agent systems as deployment moves beyond controlled environments.
- Growing interest in teacher-centered and education-focused multi-agent systems that support human educators rather than replacing them.