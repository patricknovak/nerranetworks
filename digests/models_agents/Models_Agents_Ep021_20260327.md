**Models & Agents**
**Date:** March 27, 2026

**HOOK:** New arXiv papers expose critical flaws in how we evaluate depression-detection models, LLM pruning, and verbalized confidence.

**What You Need to Know:** Today's cs.CL batch reveals that many impressive medical AI results may be artifacts of interviewer prompts rather than genuine participant signals, while pruning works for classification but breaks generation due to probability-space amplification. Several papers also show that fine-tuning small models on domain data delivers outsized gains in systematic review screening and low-resource medical transcription. Pay attention to the recurring theme: many current evaluation setups are contaminated by dataset artifacts.

━━━━━━━━━━━━━━━━━━━━
### Top Story
A new analysis of three public depression detection datasets (ANDROIDS, DAIC-WOZ, E-DAIC) reveals a systematic bias where models trained on interviewer turns achieve high classification scores by exploiting fixed prompts and positions rather than learning from participant language. The researchers demonstrate that restricting models to only participant utterances forces the model to rely on genuine linguistic cues, distributing decision evidence more broadly across the conversation. This cross-dataset, architecture-agnostic bias appears in semi-structured clinical interviews where consistency in interviewer prompts inadvertently creates exploitable script artifacts. The work emphasizes the need for analyses that localize decision evidence by time and speaker. Practitioners building clinical AI should immediately audit whether their models are listening to patients or interviewers.

Source: https://arxiv.org/abs/2603.24651

━━━━━━━━━━━━━━━━━━━━
### Model Updates
**When Consistency Becomes Bias: Interviewer Effects in Semi-Structured Clinical Interviews**
Models achieve strong depression detection performance without using participant language by exploiting fixed interviewer prompts. Restricting to participant utterances reveals the true linguistic signals. This finding has immediate implications for any medical conversation AI.

Source: https://arxiv.org/abs/2603.24651

**Demystifying When Pruning Works via Representation Hierarchies**
Pruning works well for non-generative tasks because embedding and logit spaces remain robust, but the nonlinear logit-to-probability transformation amplifies deviations during generation. The categorical-token probability subspace explains why retrieval and multiple-choice tasks survive pruning better. Code is available for further experimentation.

Source: https://arxiv.org/abs/2603.24652

**Fine-Tuning A Large Language Model for Systematic Review Screening**
Fine-tuning a 1.2B open-weight LLM on >8500 human-rated titles and abstracts produced an 80.79% improvement in weighted F1 over the base model. On the full 8,277-study dataset it reached 86.40% agreement with humans and 91.18% true positive rate with perfect inference-run consistency. This demonstrates clear value in fine-tuning even small models for high-stakes screening tasks.

Source: https://arxiv.org/abs/2603.24767

**Evaluating Fine-Tuned LLM Model For Medical Transcription With Small Low-Resource Languages Validated Dataset**
Fine-tuning LLaMA 3.1-8B on a small Finnish clinical conversation corpus yielded strong semantic similarity (BERTScore F1 = 0.8230) despite low n-gram overlap. The work supports feasibility of privacy-oriented domain-specific models for low-resource languages in clinical documentation.

Source: https://arxiv.org/abs/2603.24772

━━━━━━━━━━━━━━━━━━━━
### Agent & Tool Developments
**LLM-Driven Reasoning for Constraint-Aware Feature Selection in Industrial Systems**
Model Feature Agent (MoFA) uses semantic and quantitative feature information in structured prompts to perform sequential, reasoning-based feature selection under operational constraints. It delivered accuracy gains plus reduced feature complexity in True Interest prediction, discovered high-order interactions improving online engagement, and selected compact subsets that boosted both accuracy and inference speed in notification prediction. Shows practical value of LLM reasoning for production ML systems where labeled data is scarce.

Source: https://arxiv.org/abs/2603.24979

**Prompt Attack Detection with LLM-as-a-Judge and Mixture-of-Models**
Lightweight general-purpose LLMs (including gemini-2.0-flash-lite-001) can act as effective low-latency security judges when guided through structured reasoning (intent decomposition, safety-signal verification, harm assessment, self-reflection). The approach is already deployed in production as a centralized guardrail for public service chatbots in Singapore. A Mixture-of-Models variant provided only modest gains.

Source: https://arxiv.org/abs/2603.25176

━━━━━━━━━━━━━━━━━━━━
### Practical & Community
**Synthetic Rewriting as a Quality Multiplier: Evidence from Portuguese Continued Pretraining**
Controlled study on Portuguese data shows synthetic rewriting acts primarily as a *quality multiplier* rather than a substitute for curation. Rewriting high-quality data gave +3.4 NPM at 7B scale while rewriting low-quality data gave only +0.5. Effect is scale-dependent; unmodified low-quality data performed comparably to rewritten high-quality data at 1.1B scale.

Source: https://arxiv.org/abs/2603.24826

**Closing the Confidence-Faithfulness Gap in Large Language Models**
Mechanistic interpretability work shows calibration and verbalized confidence are encoded linearly but orthogonally. Prompting models to reason while verbalizing confidence creates a "Reasoning Contamination Effect" that worsens miscalibration. Introduces a two-stage adaptive steering pipeline that substantially improves calibration alignment.

Source: https://arxiv.org/abs/2603.25052

**Do LLMs Know What They Know? Measuring Metacognitive Efficiency with Signal Detection Theory**
New evaluation framework using Type-2 Signal Detection Theory (meta-d' and M-ratio) reveals that metacognitive efficiency varies substantially across models even when raw accuracy is similar. Efficiency is domain-specific and temperature mainly shifts criterion rather than sensitivity. AUROC₂ and M-ratio produce completely inverted model rankings, showing they answer different questions.

Source: https://arxiv.org/abs/2603.25112

━━━━━━━━━━━━━━━━━━━━
### Under the Hood: Representation Hierarchies in Pruning
Everyone talks about pruning as if it's a simple "remove low-magnitude weights" switch that should work equally everywhere. In reality, it's a story about three distinct representation spaces that respond differently to perturbation.

The core insight is that embedding (hidden states) and logit (pre-softmax) spaces are surprisingly robust to pruning. The trouble begins in the nonlinear transformation from logits to probabilities. Small deviations in logit space get amplified nonlinearly, then accumulate across autoregressive steps during generation, producing the well-known degradation in generative tasks.

For non-generative work like retrieval or multiple-choice, you mostly operate in the more stable embedding space or make single categorical decisions in probability space, which explains why pruning "works" there. The categorical-token probability subspace itself is also relatively stable, giving classification tasks a safety margin that generation lacks.

This decomposition gives practitioners a clear decision framework: prune aggressively for embedding-heavy or single-step tasks; be far more cautious with long-form generation. The quality gain from pruning often disappears or reverses exactly where token-by-token probability chaining matters most.

The gotcha that bites most teams is assuming uniform robustness across the model's computational graph. Always measure perturbation effects separately in embedding, logit, and probability spaces for your specific workload.

━━━━━━━━━━━━━━━━━━━━
### Things to Try This Week
- Try fine-tuning a small open-weight model (1.2B–8B) on your own domain screening or transcription data — the papers show dramatic gains are possible even with modest datasets
- Audit any clinical or semi-structured interview models you run to check if they're exploiting interviewer prompts rather than participant language
- Experiment with representation-space analysis when pruning models: measure embedding vs logit vs probability stability for your specific tasks
- Test MoFA-style LLM reasoning for feature selection in your industrial ML pipelines where constraints and limited labels are common
- Compare metacognitive efficiency (M-ratio) rather than just calibration on your domain — you may discover your "well-calibrated" model actually doesn't know what it doesn't know

━━━━━━━━━━━━━━━━━━━━
### On the Horizon
- More work expected on localizing decision evidence by speaker and time in conversational medical AI
- Continued exploration of synthetic data as quality multiplier vs replacement across additional languages
- Further mechanistic interpretability studies on verbalized confidence and reasoning contamination effects
- Expansion of Type-2 Signal Detection Theory frameworks to more models and domains for better metacognition measurement