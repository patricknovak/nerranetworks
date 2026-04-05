**HOOK:** AutoAgent autonomously optimizes its own harness using the same model to reach #1 on Terminal-Bench and financial modeling in under 24 hours.

**What You Need to Know:** The open-source AutoAgent project demonstrates that the biggest limiter for agent performance isn't the underlying model but the quality of the harness (tools, prompts, and evaluation loops). By creating a meta-agent that iteratively tweaks and tests configurations, it turns any task into a self-improving domain expert. This week also saw strong community validation of Gemma 4 models as practical local agents, particularly the 26B-A4B MoE variant for constrained hardware.

━━━━━━━━━━━━━━━━━━━━
### Top Story
Kevin Gu open-sourced **AutoAgent**, an AI system that builds a Meta agent capable of autonomously upgrading its own harness (tools, system prompts, and evaluation logic) until it ranks #1 on its target task. The same base model (Claude) is used both for execution and evaluation, which the author credits with providing superior failure analysis and iteration quality compared to human oversight. It was demonstrated topping rankings on Terminal-Bench (coding) and spreadsheet-based financial modeling within 24 hours. 

This directly addresses the widespread complaint that "agents suck" not because of model intelligence but because of brittle harnesses. Practitioners can now point this system at almost any domain-specific task and let it self-optimize. The full implementation is available on GitHub for immediate experimentation.

Source: https://github.com/kevinrgu/autoagent

━━━━━━━━━━━━━━━━━━━━
### Model Updates
**Gemma 4 31B vs Gemma 4 26B-A4B vs Qwen 3.5 27B blind eval** — r/LocalLLaMA  
A 30-question blind test (code, reasoning, analysis, communication, meta-alignment) judged by Claude Opus 4.6 showed Qwen 3.5 27B winning 46.7% of matchups but suffering format/refusal failures on 10% of questions. Both Gemma 4 31B and the 26B-A4B MoE variant achieved identical 8.82 average scores, with Gemma 4 31B dominating communication and the MoE variant showing strong efficiency when it didn't error out. Gemma 4 31B also placed 3rd on the FoodTruck Bench, beating GLM 5, Qwen 3.5 397B, and several Claude Sonnet variants.

Source: https://www.reddit.com/r/LocalLLaMA/comments/1scwos6/gemma_4_31b_vs_gemma_4_26ba4b_vs_qwen_35_27b/

**Gemma 4 shines as local Windows and Mac agent** — r/LocalLLaMA  
Community reports highlight Gemma 4 (especially the 26B-A4B MoE) as an exceptionally strong local agent for Windows and 16GB hardware. Users report it outperforms Qwen 3.5 27B in real-world coding speed, multilingual support, Systems & DevOps tasks, and creative work such as SVG generation and building a Doom-style raycaster in HTML/JS with far fewer prompts and less looping behavior.

Source: https://www.reddit.com/r/LocalLLaMA/comments/1scx7la/gemma4_is_the_beast_as_windows_agent/

**Alibaba's Qwen team releases new reasoning algorithm** — The Decoder  
The Qwen team introduced a reinforcement learning variant that weights each reasoning step by its influence on future tokens rather than applying uniform rewards. This change reportedly doubles the length of coherent thought processes in reasoning models.

Source: https://the-decoder.com/alibabas-qwen-team-makes-ai-models-think-deeper-with-new-algorithm/

━━━━━━━━━━━━━━━━━━━━
### Agent & Tool Developments
**AutoAgent self-improving harness** — r/artificial  
The core contribution is treating the agent harness itself as the optimizable artifact. A meta-agent iteratively modifies prompts, tool definitions, and evaluation criteria, using the same model to critique its own performance. This removes humans as the bottleneck for domain-specific agent training.

Source: https://www.reddit.com/r/artificial/comments/1scx9kw/auto_agent_self_improving_domain_expertise_agent/

**OpenClaw with local models on mid-range hardware** — r/LocalLLaMA  
A one-click OpenClaw setup with Gemma 4 and Qwen 3.5 using TurboQuant caching and context warming now runs viable local agents on 16GB MacBook Air / Mac Mini at 10-15 tokens per second. Tool calling reliability was improved through patches to the llama.cpp TurboQuant implementation.

Source: https://www.reddit.com/r/LocalLLaMA/comments/1sciyfg/running_openclaw_with_gemma_4_turboquant_on/

━━━━━━━━━━━━━━━━━━━━
### Practical & Community
**Kreuzberg v4.7.0 document intelligence library** — r/LocalLLaMA  
The Rust-core extraction library now supports 248 languages via tree-sitter, performs AST-level code intelligence (functions, classes, imports, symbols), and dramatically improved Structural F1 scores across 23 formats (LaTeX 0%→100%, XLSX 30%→100%, PDF tables 15.5%→53.7%). It ships as an OpenWebUI backend and includes TOON format for 30-50% lower token usage in agent prompts.

Source: https://www.reddit.com/r/LocalLLaMA/comments/1scv46p/improved_markdown_quality_code_intelligence_for/

**scan-for-secrets 0.1** — Simon Willison's Weblog  
Simon Willison released a simple Python tool that scans directories for API keys and secrets, including common encodings and escaping variants. Built with Claude Code via README-driven development and red/green TDD, it helps safely publish transcripts of local agent sessions.

Source: https://simonwillison.net/2026/Apr/5/scan-for-secrets-3/#atom-everything

**Cadenza: Wandb integration for agents** — r/artificial  
New CLI and Python SDK that imports Wandb projects, indexes runs by config and metrics, and returns only high-performing experiments to agents. Designed to reduce context rot and enable better exploration/exploitation tradeoffs in autonomous research loops.

Source: https://www.reddit.com/r/artificial/comments/1scmaxt/p_cadenza_connect_wandb_logs_to_agents_easily_for/

━━━━━━━━━━━━━━━━━━━━
### Under the Hood: Self-Improving Agent Harnesses

Everyone talks about "self-improving agents" as if the model simply gets smarter through some magical feedback loop. In practice, the breakthrough in AutoAgent is that it treats the harness — the system prompt, tool schemas, error recovery logic, and evaluation criteria — as the primary optimization target rather than the weights.

The core insight is that most agent failures are systematic and reproducible once you have a reliable critic. By using the same model family for both acting and judging, the critic shares the exact tokenization, instruction-following quirks, and failure modes of the executor. This creates tighter feedback than a human or different-model judge can provide. The meta-agent then performs a form of program synthesis over the configuration space: mutating prompts, adjusting JSON schemas, changing tool descriptions, and measuring success on a validation set.

This adds overhead (each iteration requires multiple full test runs) but removes the human bottleneck that traditionally made domain-specific agent tuning expensive. The quality gain is most pronounced on long-horizon or highly structured tasks where brittle tool calling or prompt drift kills performance. The gotcha that bites most teams is that the meta-optimization process itself needs careful bounding — without limits on search depth or compute budget, it can simply produce ever-more-complex but fragile configurations.

When to use this approach: for any recurring domain task where you can define clear success metrics and are willing to spend 10-100x more upfront compute to get a specialized harness. The alternative (hand-crafting prompts across many models) scales poorly as task complexity grows.

━━━━━━━━━━━━━━━━━━━━
### Things to Try This Week
- **Try AutoAgent** on one of your existing agent tasks — point the meta-optimizer at your current harness for Terminal-Bench style coding or data analysis and see how many iterations it takes to outperform your manual version.
- **Run Gemma 4 26B-A4B** locally (Unsloth IQ4_XS or IQ4_NL quants) for coding and vision tasks on 16GB hardware — use the recommended temperature 0.3 / min-p 0.1 settings and --image-min-tokens 300 for strong vision performance.
- **Test Kreuzberg v4.7.0** as your document extraction backend for agents — feed it code repositories or mixed PDFs/spreadsheets and compare token efficiency using the new TOON format.
- **Integrate Cadenza** with your Wandb projects if you're running autonomous research agents — it dramatically reduces context rot by surfacing only high-performing experiment configurations.
- **Use scan-for-secrets** before publishing any local Claude Code or agent transcripts — especially useful if you're sharing detailed logs from AutoAgent or OpenClaw runs.

━━━━━━━━━━━━━━━━━━━━
### On the Horizon
- Expect further releases and quant optimizations for Gemma 4 models as the community continues to push local agent performance on consumer hardware.
- Qwen team’s per-step weighted RL technique will likely appear in future Qwen 3.6 releases, potentially improving long-chain reasoning reliability.
- More agent frameworks are expected to adopt structured document intelligence backends like Kreuzberg now that it offers clean AST-level code extraction and OpenWebUI integration.
- Continued experimentation with same-model critic loops in open-source agent projects as the AutoAgent approach spreads.