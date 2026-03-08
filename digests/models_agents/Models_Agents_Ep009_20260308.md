# Models & Agents
**Date:** March 08, 2026

**HOOK:** Meta's new research trains multimodal AI on unlabeled video, challenging assumptions about text-heavy scaling.

**What You Need to Know:** Meta FAIR and NYU researchers have demonstrated that unlabeled video could be the next big frontier for training multimodal models, potentially bypassing the drying up of high-quality text data by leveraging vast video datasets for better generalization. Meanwhile, a study highlights how AI agent benchmarks are overly focused on coding tasks, missing opportunities in broader labor markets, and a new tutorial offers a hands-on framework for building advanced cognitive agents with memory and validation. This week, pay attention to how video data might shift multimodal training paradigms and explore agent frameworks that emphasize planning and real-world applicability beyond just programming.

━━━━━━━━━━━━━━━━━━━━
### Top Story
Meta FAIR and New York University researchers trained a multimodal AI model from scratch using unlabeled video data, revealing that common assumptions about architecture and training—like the need for heavy text supervision—don't always hold. The model, built on a vision-language setup, showed strong performance in tasks like image classification and visual question answering by tapping into video's temporal dynamics, outperforming text-only baselines in generalization while using less curated data. Compared to existing multimodal giants like GPT-4V or Gemini, this suggests a path to scaling without relying on depleting text corpora, potentially making training more efficient and accessible. Developers building vision AI can now experiment with similar unlabeled video approaches to enhance model robustness in real-world scenarios. Keep an eye on Meta's upcoming releases that might integrate this into Llama variants, and try incorporating video datasets into your fine-tuning pipelines for multimodal RAG systems. This is a genuine step forward for handling data scarcity, though it still requires massive compute for video processing.
Source: https://the-decoder.com/llm-text-data-is-drying-up-but-meta-points-to-unlabeled-video-as-the-next-massive-training-frontier/

━━━━━━━━━━━━━━━━━━━━
### Model Updates
**AI Agent Benchmarks Obsess Over Coding While Ignoring 92% of the US Labor Market, Study Finds: The Decoder**  
A comprehensive study analyzed AI agent benchmarks and found they disproportionately emphasize coding tasks, covering only 8% of the US labor market while neglecting areas like healthcare, education, and retail. This skew limits progress in developing versatile agents, as benchmarks like those in LangGraph or AutoGPT often prioritize code generation over diverse skills, leading to overhyped claims about agentic AI's real-world readiness. For practitioners, this matters because it highlights the need to create or adapt benchmarks for non-coding domains to build more balanced agents—think expanding beyond GitHub-centric evals to simulate everyday workflows.  
Source: https://the-decoder.com/ai-agent-benchmarks-obsess-over-coding-while-ignoring-92-of-the-us-labor-market-study-finds/

━━━━━━━━━━━━━━━━━━━━
### Agent & Tool Developments
**Building Next-Gen Agentic AI: A Complete Framework for Cognitive Blueprint Driven Runtime Agents with Memory Tools and Validation: MarkTechPost**  
This tutorial introduces a full framework for creating runtime agents driven by cognitive blueprints, including structured elements for identity, goals, planning, memory access, tool calling, and output validation, enabling agents to plan, execute, and self-improve systematically. It's an improvement over basic setups in frameworks like CrewAI or Microsoft AutoGen, as it incorporates memory tools and validation loops for more reliable multi-step tasks, reducing hallucinations and enhancing alignment. You can try it today by following the step-by-step guide to build your own agent—start with defining a blueprint in JSON and integrating it with open-source LLMs like Llama 3.  
Source: https://www.marktechpost.com/2026/03/07/building-next-gen-agentic-ai-a-complete-framework-for-cognitive-blueprint-driven-runtime-agents-with-memory-tools-and-validation/

━━━━━━━━━━━━━━━━━━━━
### Things to Try This Week
- Try incorporating unlabeled video datasets into your multimodal training pipelines with models like Llama or CLIP variants—it's worth exploring for better generalization in vision tasks without heavy text annotation.
- Check out the cognitive blueprint framework from the MarkTechPost tutorial if you're building agents for planning-heavy workflows, as it adds memory and validation to make outputs more reliable than standard LangChain setups.
- Compare agent benchmarks beyond coding by adapting open evals from the study—test your agents on non-programming tasks like simulated retail scenarios to identify gaps in real-world applicability.
- Experiment with video-based pretraining for RAG systems—pair it with vector databases like Pinecone to see if it boosts performance in dynamic content retrieval over text-only embeddings.

━━━━━━━━━━━━━━━━━━━━
### On the Horizon
- Meta's potential integration of video training into future Llama releases, building on this research for more efficient multimodal models.
- Expanded agent benchmarks targeting non-coding labor sectors, possibly influencing updates to frameworks like LangGraph or AutoGen.
- Community-driven extensions of the cognitive blueprint framework, including integrations with tools like Semantic Kernel for edge deployment.
- Regulatory discussions on data sourcing for AI training, especially as video datasets raise new privacy and alignment concerns.