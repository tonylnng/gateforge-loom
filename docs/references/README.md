# External References

Primary-source papers and external documents that inform Gateforge-Loom's
design. Each entry lists the local copy, the canonical source, and which parts
of the stack it influences.

> **Why keep local copies?** Preprints get revised and links rot. A pinned
> local copy guarantees the design rationale stays reproducible. Always cite
> the canonical source (below) in addition to the local file.

---

## Index

| File | Title | Authors / Venue | Date | Informs |
|---|---|---|---|---|
| [`DMoE-2606.14243v1.pdf`](DMoE-2606.14243v1.pdf) | Decoupled Mixture-of-Experts for Parametric Knowledge Injection | Baoqing Yue, Weihang Su, Qingyao Ai, Yichen Tang, Changyue Wang, Jiacheng Kang, Jingtao Zhan, Yiqun Liu — Tsinghua University (cs.CL) | 12 Jun 2026 | `hermes-dmoe` (Knowledge layer) |

---

## DMoE — Decoupled Mixture-of-Experts

- **Canonical source:** [arXiv:2606.14243](https://arxiv.org/abs/2606.14243)
  ([PDF](https://arxiv.org/pdf/2606.14243v1) · [HTML](https://arxiv.org/html/2606.14243v1))
- **DOI:** [10.48550/arXiv.2606.14243](https://doi.org/10.48550/arXiv.2606.14243)
- **Local copy:** [`DMoE-2606.14243v1.pdf`](DMoE-2606.14243v1.pdf)

### One-line summary
A modular architecture for **parametric knowledge injection** that decouples
**both the experts and the router** from a **frozen** base model: external
knowledge becomes independently-updatable LoRA experts, activated by a
training-free, uncertainty-gated router, and merged only into the final-layer
FFN to preserve KV-cache reuse.

### Key design points (as implemented in Gateforge-Loom's `hermes-dmoe`)

| Aspect | Paper detail |
|---|---|
| Expert | One LoRA adapter per knowledge unit — rank 4, α = 16, lr 1e-5, 1 epoch, base frozen |
| Placement | Final-layer FFN only (keeps earlier hidden states / KV-cache valid) |
| Construction | Per doc: 1 paraphrase + 3 generated Q&A pairs; no gold answers/labels |
| Router | Training-free BM25 over each expert's text surrogate `D_i`; incrementally updatable |
| Trigger | Token-entropy `TU_t = -Σ p_t(v) log p_t(v) > τ` (default `τ = 2.0`) |
| Selection | `E_sel = Top-k BM25(q_t, D_i)`, default `k = 3` |
| Merge | `θ_eff_t = θ + Σ_{E_i ∈ E_sel} Δθ_i` |
| Benchmarks | HotpotQA, ComplexWebQuestions, Quasar-T, StrategyQA |
| Results | Best/tied-best on 11 of 14 effectiveness metrics; ~3× faster, ~1.6–1.9× less GPU than FLARE |

### Where it lands in this repo
- Concept & DMoE diagrams: [`../../README.md`](../../README.md#5-dmoe-diagram-parametric-knowledge-injection)
- Design rationale: [`../architecture.md`](../architecture.md#why-dmoe-for-parametric-memory)
- Component spec: [`../components.md`](../components.md#-hermes-dmoe--knowledge-dmoe)
- API contract: [`../api-contract.md`](../api-contract.md#knowledge--hermes-dmoe-port-8004)

---

## Adding a new reference

1. Drop the file here with a stable, descriptive name (include the
   identifier/version, e.g. `DMoE-2606.14243v1.pdf`).
2. Add a row to the [Index](#index) table above.
3. Add a short section with the canonical source link and a one-line summary.
4. Link it from whichever doc it informs.
