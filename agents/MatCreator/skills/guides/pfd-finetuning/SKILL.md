---
name: pfd-finetuning
description: Iterative workflow that fine-tunes pre-trained ML force fields using DFT-labeled data via active learning.
metadata:
  dependent_skills:
    - machine-learning-force-field
    - dft-calculation
    - molecular-dynamics
    - atomic-structure
    - deepmd
    - abacus
  tags:
    - iterative
    - active-learning
    - fine-tune
---

Coordinate iterative fine-tuning of ML force fields from a pre-trained model.

Standard loop:
1. Structure building
2. MD exploration
3. Entropy-based data curation
4. DFT Labeling
5. Training
6. Convergence check
7. Repeat until criteria or max iterations.

Key parameters to confirm:
- max iterations (default:1), convergence criterion (default: RMSE_energy = 5 meV/atom)
- initial structure, supercell size (default: 1 x 1 x 1), number of perturbations (default: 1), perturbation settings. 
- MD ensemble (default: NVT/NPT), temperature (default: 300 K), timestep (default: 2 fs), steps (default: 1 ps), save interval (default: 50), pressure (for NPT ensemble, default: 0 GPa)
- curation max_sel(number of frames sent for DFT calculation, default:30), chunk_size(default: 10)
- DFT parameters: kspacing (default: 0.14 Angstrom)
- training epochs (default: 100) and train/test split (default: 0.9/0.1)
