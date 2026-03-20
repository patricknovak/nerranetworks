**HOOK:** LlamaIndex drops LiteParse, a spatial PDF parser built specifically for agentic RAG workflows.

**What You Need to Know:** Today's biggest practical release is LlamaIndex's new LiteParse library, which tackles the persistent data ingestion bottleneck in agentic systems. Multiple arXiv papers also surfaced strong advances in uncertainty-calibrated RAG, deterministic evidence selection, and dynamic knowledge integration via DynaRAG. Google expanded its Universal Commerce Protocol with cart, catalog, and loyalty features aimed at making shopping agents far more capable.

━━━━━━━━━━━━━━━━━━━━
### Top Story
LlamaIndex has released LiteParse, an open-source CLI and TypeScript-native library designed for spatial PDF parsing in AI agent workflows. 

The core problem it solves is that complex PDFs remain the highest-latency, most expensive part of modern RAG pipelines — even as LLMs themselves have become relatively cheap. LiteParse focuses on preserving layout and spatial relationships that most parsers destroy, giving agents much richer context for document-heavy tasks.

This directly matters for anyone building production agents that need to reason over contracts, research papers, financial reports, or technical manuals. You can now parse these documents more accurately and faster without throwing everything into a massive unstructured blob.

Developers should try the new CLI today on their trickiest PDFs and integrate the TypeScript library into existing LlamaIndex agent flows. Watch for rapid community extensions as this becomes the new default ingestion layer for agentic RAG.

Source: https://www.marktechpost.com/2026/03/19/llamaindex-releases-liteparse-a-cli-and-typescript-native-library-for-spatial-pdf-parsing-in-ai-agent-workflows/

━━━━━━━━━━━━━━━━━━━━
### Model Updates
**Theory of Mind in LLMs: GPT-4o stands out**  
A new arXiv paper tested five LLMs against humans using the Strange Stories paradigm. Earlier and smaller models were heavily affected by the number of inferential cues and vulnerable to distracting information, while GPT-4o achieved high accuracy and strong robustness, performing comparably to human controls even in the hardest conditions. This is one of the clearest demonstrations yet of genuine capability differences at scale.  
Source: https://arxiv.org/abs/2603.18007

**PowerFlow: Principled unsupervised RL for LLMs**  
Researchers introduced PowerFlow, which reformulates unsupervised fine-tuning as distribution matching using a length-aware Trajectory-Balance objective with GFlowNets. It can sharpen the distribution (α > 1) for stronger reasoning or flatten it (α < 1) for creativity, consistently outperforming existing RLIF methods and sometimes beating supervised GRPO.  
Source: https://arxiv.org/abs/2603.18363

**CONSTRUCT for real-time trustworthiness scoring**  
A new method called CONSTRUCT scores the trustworthiness of LLM structured outputs (and individual fields) in real time without needing logprobs, training data, or custom deployment. It works on complex nested JSON schemas and beats other scoring methods on a new public benchmark covering Gemini 3 and GPT-5.  
Source: https://arxiv.org/abs/2603.18014

━━━━━━━━━━━━━━━━━━━━
### Agent & Tool Developments
**DynaRAG: Bridging static and dynamic knowledge**  
DynaRAG selectively calls external APIs when retrieved documents are insufficient, using an LLM reranker, sufficiency classifier, and Gorilla v2 for tool invocation. It shows strong gains on dynamic questions in the CRAG benchmark while reducing hallucinations.  
Source: https://arxiv.org/abs/2603.18012

**Google expands Universal Commerce Protocol for shopping agents**  
Google added shopping cart, catalog, and identity/loyalty features to UCP, giving AI shopping agents persistent state and richer commerce capabilities. This is a significant step toward truly autonomous retail agents.  
Source: https://the-decoder.com/google-gives-ai-shopping-agents-cart-catalog-and-loyalty-features/

**Agentic Framework for Political Biography Extraction**  
A two-stage "Synthesis-Coding" system uses recursive agentic LLMs to gather and curate information from the web, then maps it into structured data. The synthesis stage outperforms Wikipedia and reduces bias compared to direct coding from raw sources.  
Source: https://arxiv.org/abs/2603.18010

━━━━━━━━━━━━━━━━━━━━
### Practical & Community
**Controllable Evidence Selection via Deterministic Utility Gating**  
New framework introduces Meaning-Utility Estimation (MUE) and Diversity-Utility Estimation (DUE) to make evidence selection deterministic and auditable before answer generation. It only accepts sentences that explicitly satisfy the required fact or condition, dramatically improving transparency in RAG.  
Source: https://arxiv.org/abs/2603.18011

**UCPOF: Uncertainty-calibrated prompt optimization**  
The Log-Scale Focal Uncertainty (LSFU) metric combined with first-token uncertainty drives a framework that improves accuracy by ~6% over few-shot baselines, beats full RAG, and cuts retrieval calls by over 50%. Excellent practical result for production RAG systems.  
Source: https://arxiv.org/abs/2603.18009

**TherapyGym for clinical alignment of therapy chatbots**  
New evaluation framework measures adherence to CBT techniques via the Cognitive Therapy Rating Scale and assesses safety risks. Models trained with CTRS and safety rewards improved dramatically (0.10→0.60 on expert ratings). Includes TherapyJudgeBench for calibration against clinicians.  
Source: https://arxiv.org/abs/2603.18008

━━━━━━━━━━━━━━━━━━━━
### Under the Hood: Agentic RAG Failure Modes
Everyone talks about agentic RAG like the main challenge is just making the LLM smarter. In practice, the real killers are silent failure modes that don't crash but quietly destroy performance and inflate costs: Retrieval Thrash, Tool Storms, and Context Bloat.

The core insight is that once you give an agent a loop and multiple tools, its behavior becomes a search process rather than a single forward pass. Retrieval Thrash happens when the agent keeps retrieving overlapping or low-value chunks because its stopping criteria are weak. Tool Storms occur when the agent calls 15+ tools in a row without making progress, often because each tool call slightly changes the context and resets its sense of direction. Context Bloat is the natural result — the prompt grows until you're paying for 100k+ tokens of mostly redundant information.

These problems compound because they're invisible in simple accuracy metrics. A system can have 85% "success" rate while spending 7× more on inference than necessary. The engineering reality is that you need explicit monitoring for these three failure signatures (repeated retrieval of similar documents, tool call chains longer than ~6-7 steps, and context growth rate) rather than just final answer quality.

The gotcha that bites most teams is treating these as model problems instead of system problems. Better models help at the margin, but the real wins come from adding early detection, hard step budgets, utility-based retrieval gating, and explicit anti-thrash mechanisms in your agent loop. When building agentic RAG, instrument these three metrics first — everything else is secondary.

━━━━━━━━━━━━━━━━━━━━
### Things to Try This Week
- Try **LiteParse** from LlamaIndex on your worst PDF documents — especially layout-heavy contracts or research papers — to see immediate gains in agent reasoning quality.
- Test **DynaRAG** patterns (or build a simple version) if you're working with time-sensitive information that static corpora can't cover.
- Experiment with **UCPOF-style uncertainty triggering** in your existing RAG setup — you can implement a first-token uncertainty check in ~50 lines and potentially cut retrieval costs in half.
- Run your current structured output pipeline through **CONSTRUCT-style trustworthiness scoring** to see where your human review effort is best spent.
- Compare **GPT-4o vs smaller models** on Theory of Mind tasks using the Strange Stories approach — the gap is larger than most people expect.

━━━━━━━━━━━━━━━━━━━━
### On the Horizon
- More production-focused agent monitoring tools expected as Retrieval Thrash and Tool Storm research gains traction.
- Continued rapid iteration on open-source PDF parsing and document intelligence libraries following LiteParse.
- Growing interest in uncertainty-aware and deterministic RAG techniques that reduce cost while increasing reliability.
- Expansion of commerce protocols and agent-friendly APIs as companies like Google push toward practical autonomous shopping agents.