# Select a maximally diverse subset using descriptor-based filtering.

```python
from ase.io import read, write
import numpy as np
from collections import Counter
import json

def compute_simple_descriptor(atoms, cutoff=5.0, n_bins=20):
    """Compute a simple RDF-based descriptor."""
    from scipy.spatial.distance import pdist
    
    positions = atoms.positions
    cell = atoms.cell.array
    pbc = atoms.pbc
    
    # Minimum image convention
    if np.any(pbc):
        # Simple approach: use ASE neighbor list
        from ase.neighborlist import neighbor_list
        i, j, d, S = neighbor_list('ijdS', atoms, cutoff=cutoff)
        
        # Histogram distances
        if len(d) > 0:
            hist, _ = np.histogram(d, bins=n_bins, range=(0, cutoff))
            return hist.astype(float) / (len(d) + 1e-10)
        else:
            return np.zeros(n_bins)
    else:
        distances = pdist(positions)
        distances = distances[distances < cutoff]
        if len(distances) > 0:
            hist, _ = np.histogram(distances, bins=n_bins, range=(0, cutoff))
            return hist.astype(float) / (len(distances) + 1e-10)
        else:
            return np.zeros(n_bins)

def entropy_based_selection(structures, reference_structures=None, 
                           max_sel=50, chunk_size=10, cutoff=5.0):
    """Select diverse structures using entropy maximization."""
    
    # Compute descriptors
    descriptors = []
    for atoms in structures:
        desc = compute_simple_descriptor(atoms, cutoff=cutoff)
        descriptors.append(desc)
    descriptors = np.array(descriptors)
    
    if reference_structures:
        ref_descriptors = []
        for atoms in reference_structures:
            desc = compute_simple_descriptor(atoms, cutoff=cutoff)
            ref_descriptors.append(desc)
        ref_descriptors = np.array(ref_descriptors)
    else:
        ref_descriptors = np.array([]).reshape(0, descriptors.shape[1])
    
    selected_indices = []
    selected_descriptors = []
    entropy_history = {}
    
    n_selected = 0
    iteration = 0
    
    while n_selected < min(max_sel, len(structures)):
        # Compute entropy for each candidate
        if len(selected_descriptors) == 0:
            # First selection: pick the one most different from reference
            if len(ref_descriptors) > 0:
                distances = np.array([
                    np.min(np.linalg.norm(ref_descriptors - d, axis=1))
                    for d in descriptors
                ])
                best_idx = np.argmax(distances)
            else:
                best_idx = 0
        else:
            # Compute entropy contribution for each remaining candidate
            remaining_indices = [i for i in range(len(structures)) 
                               if i not in selected_indices]
            
            entropies = []
            for idx in remaining_indices:
                d = descriptors[idx]
                # Distance to nearest selected
                if len(selected_descriptors) > 0:
                    min_dist = np.min(np.linalg.norm(
                        np.array(selected_descriptors) - d, axis=1))
                else:
                    min_dist = 1.0
                entropies.append(min_dist)
            
            best_local_idx = np.argmax(entropies)
            best_idx = remaining_indices[best_local_idx]
        
        # Select this structure
        selected_indices.append(best_idx)
        selected_descriptors.append(descriptors[best_idx])
        n_selected += 1
        
        # Compute current entropy (simplified)
        if len(selected_descriptors) > 1:
            sel_array = np.array(selected_descriptors)
            pairwise_dist = np.linalg.norm(
                sel_array[:, np.newaxis, :] - sel_array[np.newaxis, :, :],
                axis=2
            )
            np.fill_diagonal(pairwise_dist, np.inf)
            min_distances = np.min(pairwise_dist, axis=1)
            entropy = np.mean(np.log(min_distances + 1e-10))
        else:
            entropy = 0.0
        
        entropy_history[f"iter_{iteration:02d}"] = float(entropy)
        iteration += 1
        
        if iteration >= max_sel:
            break
    
    # Get selected structures
    selected_structures = [structures[i] for i in selected_indices]
    
    return selected_structures, entropy_history

# Usage
input_path = "candidates.extxyz"
structures = read(input_path, index=':')
if not isinstance(structures, list):
    structures = [structures]

# Optional: load reference
reference_path = "existing_dataset.extxyz"
try:
    reference_structures = read(reference_path, index=':')
    if not isinstance(reference_structures, list):
        reference_structures = [reference_structures]
except:
    reference_structures = None

# Select diverse subset
selected, entropy_hist = entropy_based_selection(
    structures,
    reference_structures=reference_structures,
    max_sel=50,
    chunk_size=10,
    cutoff=5.0
)

# Save selected structures
output_path = "selected_diverse.extxyz"
write(output_path, selected, format='extxyz')

print(json.dumps({
    "status": "success",
    "selected_atoms": output_path,
    "num_selected": len(selected),
    "entropy": entropy_hist
}))
```