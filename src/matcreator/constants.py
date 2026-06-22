PFD_INSTRUCTIONS = """
The PFD workflow have four major steps: 
1) Exploration: generate new frames using molecular dynamics (MD) simulations. 
    You should verify the MD parameters such as temperature, duration, timestep, and ensemble before running MD simulations. 
    You also need to confirm the model style and model path to be used in the MD simulations. Please check the `calc_args` for any additional calculator parameters.
2) Data curation: select informative frames from the MD trajectory using entropy-based selection. You should verify the selection parameters such as chunk size, number of selections, k-nearest neighbors, cutoff distance, and entropy bandwidth before running the selection.
3) Data labeling: perform energy and force calculations for the selected frames. 
    For fine-tuning task, use ABACUS SCF calculation. You should verify the DFT parameters such as pseudopotentials, basis set, k-point sampling, energy cutoff, and convergence criteria before running DFT calculations.
    For distillation task, use ASE calculators (e.g., DPA). You should verify the model style, model path, and any additional calculator parameters before running the calculations.
4) Model training: fine-tune a machine learning force fields using the labeled data. You should verify the training parameters such as number of epochs, and validation split before running the training.
In theory, you can run multiple iterations of the above steps to gradually improve the model performance. However, in practice, a single iteration is often sufficient to achieve good results.
Notes: you need to verify the model style, base model path, and training strategy before training. Place them in the log header if needed.
"""



TASK_INSTRUCTIONS = {
    "pfd_finetune":PFD_INSTRUCTIONS,
    "pfd_distillation":PFD_INSTRUCTIONS,
}