---
name: materials-design
description: Iterative workflow for materials design through candidate generation, property prediction, screening, and refinement.
metadata:
  dependent_skills:
    - dft-calculation
    - structure-generation
    - mattergen-generation
    - mattergen-finetune
    - mattergen-evaluation
    - structure-conversion
    - mattersim
    - cgcnn-predictor
    - vasp
  tags:
    - materials-design
    - inverse-design
    - screening
    - generation
---

Use this guide for iterative crystal materials design workflows that involve candidate generation, structure relaxation, property prediction, screening, and optional refinement.

## Standard Loop

1. Define the design target
- Confirm the chemical system, target properties, and screening rules, including thresholds, ranking metrics, batch size, and maximum iterations.

2. Generate candidate structures
- Prefer using `mattergen` to create a batch of candidate crystals.

3. Relax generated structures
- Before screening, use `mattersim` to relax generated structures.

4. Predict properties and rank candidates
- Use an available property-prediction workflow on the screened candidate set, such as `cgcnn_predictor` or other appropriate model/tool.

5. Evaluation
- Evaluate the screened structures with the S.U.N criteria.

6. Validate with DFT
- After screening, run DFT on a few top shortlisted candidates.

### Iteration Guidance
- If the result from any of Steps 4-6 does not meet the target requirements, consider iterating the workflow.

- Multiple iteration strategies are available, and you can choose any iteration strategy based on your own analysis:
1. Run another round of generation.
2. Fine-tune the MatterGen model using CGCNN-predicted properties and then generating again with the fine-tuned model.
3. You can also propose and execute other iteration strategies.
