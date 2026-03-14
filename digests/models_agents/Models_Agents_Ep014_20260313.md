# Models & Agents
**Date:** March 13, 2026

**HOOK:** Perplexity launches "Personal Computer," a $200/month AI agent that automates emails, presentations, and app control 24/7.

**What You Need to Know:** Perplexity AI unveiled its "Personal Computer" subscription, a tireless agent handling complex tasks like email management and app automation, marking a step toward always-on AI assistants that rival enterprise tools but at consumer pricing. Meanwhile, Ukraine is sharing battlefield data for training autonomous drone models, potentially boosting real-world AI agent reliability in high-stakes environments, while Meta delays its Avocado model due to lagging behind leaders like Google and OpenAI. Developers should watch agent framework updates from Microsoft and emerging multi-agent research for scalable coordination tools this week.

━━━━━━━━━━━━━━━━━━━━
### Top Story
Ukraine has opened a platform sharing its battlefield data with allies to train AI models specifically for autonomous drones, focusing on real-time combat scenarios. This dataset includes diverse environmental and tactical information, enabling models to improve navigation, target identification, and decision-making under uncertainty—capabilities that extend beyond military use to civilian applications like search-and-rescue agents. Compared to synthetic datasets used in models like Llama or Gemini, this real-world data could reduce hallucinations in agentic systems by grounding them in verified field conditions. For AI practitioners, this means access to high-fidelity training material that could enhance agent robustness in dynamic environments, though ethical concerns around militarized AI loom large. Builders should explore integrating similar domain-specific data into frameworks like LangGraph for more reliable autonomous agents. Keep an eye on how this influences open-source drone agent projects, with potential API access for non-military R&D forthcoming.
Source: https://the-decoder.com/ukraine-provides-allies-with-a-platform-with-combat-data-for-ai-training/

━━━━━━━━━━━━━━━━━━━━
### Model Updates
**Meta Delays Avocado Model: The Decoder**  
Meta is postponing the release of its next AI model, Avocado, after internal tests showed it underperforms against Google, OpenAI, and Anthropic in key benchmarks like reasoning and multimodal tasks. This delay highlights ongoing challenges in scaling beyond Llama 3, with Avocado aiming for advanced capabilities but falling short on efficiency and accuracy metrics. For developers, this means sticking with alternatives like Gemini 1.5 or Claude 3.5 for now, but it underscores the competitive pressure driving faster iterations in open-source models.  
Source: https://the-decoder.com/meta-delays-its-next-ai-model-avocado-after-internal-tests-show-it-cant-keep-up-with-google-and-openai/

**Enhancing Value Alignment of LLMs with Multi-Agent System: cs.MA updates on arXiv.org**  
The Value Alignment System using Combinatorial Fusion Analysis (VAS-CFA) fine-tunes multiple LLMs as moral agents, fusing their outputs to better reflect diverse ethical perspectives, outperforming single-agent RLHF on pluralism metrics. It excels in handling conflicts without a centralized reward, making it a step up from vanilla alignment in models like GPT-4 or Llama, though at higher compute cost. This matters for safety-focused devs building agents that need robust, non-monolithic value handling in real-world deployments.  
Source: https://arxiv.org/abs/2603.11126

**How Intelligence Emerges: A Minimal Theory: cs.MA updates on arXiv.org**  
This paper proposes a dynamical theory for adaptive coordination in multi-agent systems, modeling agents and environments as feedback loops that ensure viability without global optimization, differing from equilibrium-based approaches in frameworks like AutoGen. It shows how persistence and dissipation lead to emergent intelligence, with linear specs illustrating stability. Practitioners should note this for designing resilient agent swarms, though it assumes dissipativity which may not hold in chaotic real-world scenarios.  
Source: https://arxiv.org/abs/2603.11560

━━━━━━━━━━━━━━━━━━━━
### Agent & Tool Developments
**Perplexity's "Personal Computer" AI Agent: The Decoder**  
Perplexity's new "Personal Computer" is a subscription-based AI agent that operates 24/7, managing emails, creating presentations, and controlling apps via tool calling, built on their search-optimized models. This improves on episodic agents in CrewAI by adding persistence and automation, though at $200/month it's pricier than open-source alternatives. Try it via their platform for workflow automation—sign up for the beta to test integrations with your email and productivity tools.  
Source: https://the-decoder.com/perplexitys-personal-computer-promises-a-tireless-ai-agent-for-200-a-month/

**What's New in Agent Skills: Microsoft Agent Framework**  
Microsoft's Agent Framework now supports code-defined skills, script execution, and Python approvals in their SDK, allowing agents to dynamically load domain expertise without file-based directories, enhancing Semantic Kernel's flexibility. This builds on prior tool calling in AutoGen, enabling more seamless multi-agent orchestration. Developers can install the updated Python SDK and experiment with defining custom skills for tasks like data analysis.  
Source: https://devblogs.microsoft.com/agent-framework/whats-new-in-agent-skills-code-skills-script-execution-and-approval-for-python/

**Model Context Protocol vs. AI Agent Skills: MarkTechPost**  
This deep dive compares MCPs, which structure tool interactions for LLMs, against agent skills that guide behavior, showing MCPs excel in execution while skills aid in knowledge access for frameworks like LangChain. The analysis reveals trade-offs in setup complexity, with MCPs offering better parallelism. Try implementing MCP in your agent setup via open-source repos to see efficiency gains in query decomposition.  
Source: https://www.marktechpost.com/2026/03/13/model-context-protocol-mcp-vs-ai-agent-skills-a-deep-dive-into-structured-tools-and-behavioral-guidance-for-llms/

━━━━━━━━━━━━━━━━━━━━
### Practical & Community
**China’s OpenClaw Boom: Artificial Intelligence Latest**  
OpenClaw, an open-source agent framework, is sparking a gold rush in China, driving cloud rentals and AI subscriptions for testing its multi-agent coordination in tasks like automation. It enables scalable agent teams without proprietary dependencies, similar to Agent Zero but with broader community adoption. Get started by cloning the repo and running demos on a basic GPU—note it may require significant resources for large-scale experiments.  
Source: https://www.wired.com/story/china-is-going-all-in-on-openclaw/

**Resolving Java Code Repository Issues with iSWE Agent: cs.MA updates on arXiv.org**  
iSWE Agent uses multi-agent RL with rule-based Java analysis to automatically resolve code issues in repositories, outperforming baselines on Java-specific benchmarks like Multi-SWE-bench. It's tailored for enterprise devs dealing with legacy Java, combining localization and editing sub-agents. Clone the project from arXiv-linked code and test on your GitHub repos, but expect limitations in non-Java languages.  
Source: https://arxiv.org/abs/2603.11356

**CogSearch: Cognitive-Aligned Multi-Agent Framework: cs.MA updates on arXiv.org**  
CogSearch is a multi-agent system for e-commerce search, using agents to decompose queries, fuse knowledge, and deliver actionable insights, outperforming single-agent baselines in complex scenarios. It mimics human cognition for better decision support. Practitioners can prototype it with LangGraph integrations—requires fine-tuning on domain data, with potential scalability issues in very large deployments.  
Source: https://arxiv.org/abs/2603.11927

━━━━━━━━━━━━━━━━━━━━
### Things to Try This Week
- Try Perplexity's "Personal Computer" for automating daily workflows like email sorting—it's a low-barrier way to experience persistent agents beyond one-off queries in tools like AutoGPT.
- Experiment with Microsoft's new Agent Skills in Python for code-defined tools—ideal if you're building custom agents in Semantic Kernel, as it simplifies dynamic skill loading.
- Test iSWE Agent on a Java repo to auto-fix issues—great for devs maintaining enterprise code, showing how multi-agent setups beat single-model approaches in specificity.
- Compare MCP vs. agent skills in a LangChain project for query handling—highlighting when structured tools outperform behavioral guidance in parallel tasks.
- Explore OpenClaw demos for multi-agent coordination—rent a cloud instance to see its edge over frameworks like CrewAI in resource-intensive environments.

━━━━━━━━━━━━━━━━━━━━
### On the Horizon
- Watch for Meta's rescheduled Avocado release, potentially with fixes to close the gap on Gemini and Claude in multimodal benchmarks.
- Expect more integrations of battlefield data into open-source drone agents, possibly via APIs for non-military AI training.
- Anticipate community expansions on OpenClaw, including fine-tuned versions for edge deployment in Asia's AI ecosystem.
- Look out for applied papers from arXiv turning into tools, like VAS-CFA for alignment in upcoming agent frameworks.