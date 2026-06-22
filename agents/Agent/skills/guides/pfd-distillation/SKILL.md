---
name: pfd-distillation
description: Iterative workflow for model distillation. Generates a light ML force field from a pre-trained or fine-tuned model via active learning.
metadata:
  dependent_skills:
    - machine-learning-force-field
    - molecular-dynamics
    - atomic-structure
    - deepmd
  tags:
    - iterative
    - active-learning
    - distillation
---

Generate a light ML force field from a pre-trained or fine-tuned model by distillation.

Standard loop:
1. Structure building
2. MD exploration
3. Entropy-based data curation
4. Labeling using a teacher model (e.g., pre-trained DPA model or fine-tuned DPA model)
5. Training a student model from scratch using the labeled data
6. Convergence check
7. Repeat until criteria or max iterations.

Key parameters to confirm:
- task type (fine-tune/distill), max iterations (default=1), convergence criterion (default to 5 meV/atom)
- initial structure, supercell size (default to 1x1x1), perturbation settings
- MD ensemble/temperature/time/steps/save interval (default to NVT/300K/0.5ps/)
- curation max_sel(default=30)/chunk_size(default=10)
- labeling setup (predicting head for the teacher model)
- training epochs (default: 100) and split
