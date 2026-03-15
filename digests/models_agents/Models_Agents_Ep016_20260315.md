# Models & Agents
**Date:** March 15, 2026

**HOOK:** RL agents scaled to 1,024 layers unlock emergent parkour skills from basic failures.

**What You Need to Know:** Researchers have pushed reinforcement learning agents to unprecedented depths of up to 1,024 network layers, yielding 2x to 50x performance gains and entirely new behaviors like advanced locomotion in self-supervised setups. Meanwhile, Princeton's OpenClaw-RL framework turns casual interactions into training data for agents, and Codewall demonstrated how agents can hack systems while testing security. Pay attention this week to how deeper networks and interactive training could make agents more capable for real-world tasks like robotics or automation.

━━━━━━━━━━━━━━━━━━━━
### Top Story
A research team scaled reinforcement learning (RL) agents by increasing network depth from the typical 2-5 layers up to 1,024 layers, achieving 2x to 50x performance improvements in self-supervised environments. This goes beyond standard RL algorithms like PPO or DQN, where deeper networks traditionally caused training instability, but here they enabled emergent behaviors such as transitioning from clumsy falls to fluid parkour in simulated humanoid tasks. Compared to shallower models, these deep agents show better generalization without explicit reward engineering. Developers building robotics or game AI can now experiment with deeper architectures for more sophisticated autonomous behaviors, potentially reducing the need for massive datasets. Keep an eye on open-source implementations of this scaling technique, and try integrating it with frameworks like Stable Baselines3 for your own RL projects. What to watch: Further benchmarks on real hardware and integrations with multimodal inputs like vision.
Source: https://the-decoder.com/rl-agents-go-from-face-planting-to-parkour-when-researchers-keep-adding-network-layers/

━━━━━━━━━━━━━━━━━━━━
### Model Updates
**No major model releases today:** With the focus on agent advancements, we're light on foundation model updates—check back for potential drops from labs like OpenAI or Anthropic.

━━━━━━━━━━━━━━━━━━━━
### Agent & Tool Developments
**OpenClaw-RL trains AI agents "simply by talking," converting every reply into a training signal: The Decoder**  
Princeton's new OpenClaw-RL framework captures feedback from everyday interactions—like chats, terminal commands, or GUI actions—and turns them into continuous training signals for AI agents, requiring just a few dozen interactions for noticeable improvements. This improves on traditional agent frameworks like LangChain or AutoGPT by not discarding valuable live data, enabling faster adaptation without large-scale RLHF setups. You can try it today by downloading the open-source code from their GitHub repo and integrating it with your existing agent workflows for tasks like personalized assistants.  
Source: https://the-decoder.com/openclaw-rl-trains-ai-agents-simply-by-talking-converting-every-reply-into-a-training-signal/

**Codewall's AI agent hacked an AI recruiter, then impersonated Trump to test its voice bot's guardrails: The Decoder**  
Codewall showcased an AI agent that infiltrated an AI recruiting platform in under an hour, then used voice synthesis to impersonate figures like Trump for red-teaming the system's safeguards. This highlights evolving agent capabilities in areas like browser automation and social engineering tests, building on tools like AutoGen or Semantic Kernel but emphasizing security vulnerabilities in agentic systems. Developers can explore similar setups using open agent frameworks to test their own apps' defenses—start with Codewall's demo code if available.  
Source: https://the-decoder.com/codewalls-ai-agent-hacked-an-ai-recruiter-then-impersonated-trump-to-test-its-voice-bots-guardrails/

━━━━━━━━━━━━━━━━━━━━
### Practical & Community
**No standout community projects today:** The articles emphasize research and demos—look for GitHub repos tied to these for hands-on tinkering.

━━━━━━━━━━━━━━━━━━━━
### Things to Try This Week
- Try scaling your RL agents to deeper layers (up to 1,024) using techniques from the research for robotics sims—it's a game-changer for emergent behaviors compared to standard 5-layer setups.
- Integrate OpenClaw-RL into a LangChain agent for interactive training via chat—see quick improvements in tasks like code debugging with minimal data.
- Red-team your own AI systems with agentic hacks inspired by Codewall's demo—use tools like CrewAI to simulate vulnerabilities in voice or recruitment bots.
- Experiment with self-supervised RL in environments like MuJoCo to replicate the parkour emergence—compare performance against baselines like PPO.

━━━━━━━━━━━━━━━━━━━━
### On the Horizon
- Potential open-source releases of deep RL scaling code from the research team, enabling community fine-tuning.
- Beta expansions for OpenClaw-RL integrations with popular frameworks like Microsoft AutoGen.
- More red-teaming reports on agent security, possibly from conferences like NeurIPS 2026.
- Upcoming benchmarks comparing deep RL agents to foundation models like Llama 3 for hybrid agentic tasks.