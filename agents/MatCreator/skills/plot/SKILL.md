---
name: plot
description: Skill for scientific plotting using matplotlib. Generates, executes, and verifies publication-quality plots directly via run_python and run_bash.
metadata:
  tools:
    - run_bash
    - run_python
    - show_plot
  tags:
    - PLOT
    - MATPLOTLIB
    - UTILITY
---

## Workflow

1. **Determine output directory**
   Use `run_python` to build a unique timestamped output directory. First try `plots/` relative to the current working directory; fall back to `$MATCLAW_WORKSPACE/plots/` if cwd is not writable:
   ```python
   import os, datetime, random
   tag = datetime.datetime.now().strftime("%Y%m%d%H%M%S") + f"_{random.randint(100000,999999)}"
   # Prefer a plots/ subdir next to the data (cwd)
   cwd_plots = os.path.join(os.getcwd(), "plots", tag)
   try:
       os.makedirs(cwd_plots, exist_ok=True)
       output_dir = cwd_plots
   except OSError:
       ws_root = os.environ.get("MATCLAW_WORKSPACE") or os.path.expanduser("~/.workspace")
       output_dir = os.path.join(ws_root, "plots", tag)
       os.makedirs(output_dir, exist_ok=True)
   print(output_dir)
   ```
   Capture the printed path — use it as `OUTPUT_DIR` in all subsequent steps.

2. **Write the plotting script**
   Use `run_python` to write a complete Python script to `OUTPUT_DIR/plot.py`. The script must:
   - Import only allowed modules: `matplotlib`, `numpy`, `pandas`, `scipy`, `seaborn`, `ase`, `json`, `csv`, `pathlib`, `os`, `datetime`
   - Set `OUTPUT_DIR = "<absolute_path>"` at the top (hardcoded to the resolved path from step 1)
   - Load data from the **absolute** path provided by the user
   - Create the figure with `plt.subplots(figsize=..., dpi=300)`
   - Apply publication-quality formatting (axis labels with units, legend, `tight_layout()`)
   - Save with `plt.savefig(os.path.join(OUTPUT_DIR, filename), dpi=300, bbox_inches="tight")`
   - **No `plt.show()`**
   - Print the final output path at the end: `print("PLOT_PATH:", save_path)`

   Scientific context shortcuts:
   - **Band structure**: k-path x-axis with symmetry labels (Γ X L …), E − E_F on y-axis, Fermi level at y=0
   - **DOS**: energy x-axis, vertical Fermi level line, fill_between for partial DOS
   - **Convergence**: parameter on x-axis, horizontal reference line, legend per dataset
   - **MD / time-series**: time [fs/ps] x-axis, moving average if noisy
   - **Scatter / heatmap**: equal aspect if coordinates; colorbar with units

3. **Execute the script**
   ```python
   exec(open("<OUTPUT_DIR>/plot.py").read())
   ```
   Or equivalently pass the script content to `run_python`.

4. **Verify output**
   Use `run_bash` to confirm the file exists and is non-empty:
   ```bash
   ls -lh <OUTPUT_DIR>/*.png
   ```

5. **Register the plot**
   Call `show_plot(plot_path="<absolute_path_to_png>")`. This emits the structured
   `{"plot_path": "..."}` response that the UI needs to display the image.
   Only call it after `run_bash` confirms the file exists.

## Rules

- Always use absolute paths for data loading and saving.
- Use timestamps in filenames to prevent overwrites.
- If execution fails, read the error, fix the code, and retry (max 3 attempts).
- Never fabricate a `plot_path` — only report the path after `run_bash` confirms the file exists.
- Data files passed as relative paths should be resolved relative to `MATCLAW_WORKSPACE` (same logic as step 1).
