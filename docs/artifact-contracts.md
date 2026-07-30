# Genkai artifact contracts

`src/genkai/contracts/` defines the stable hand-off format between literature,
modeling, compute, dataset, and MLIP stages. Every artifact has a type and
`schema_version`, a run-relative POSIX path, SHA-256, producer and parent IDs,
plus independent execution, evidence, and validation states.

The stable artifact chain is:

```text
paper -> extraction -> modeling-plan -> structure-set
-> calculation-input -> calculation-result -> dataset
-> model -> evaluation
```

Large trajectories and checkpoints stay in files. `manifest.json` contains
only references and provenance, is written atomically, and rejects absolute or
parent-escaping artifact paths. Shared executables and checkpoints use
`ExternalResourceRef`; they remain read-only and are not copied into the run.

Execution state and evidence are deliberately separate. In particular, VASP
input preparation is `prepared`, not `dft_calculated`; simulated labels are
always `evidence_level=mock`. DeepMD and UMA production preflight reject mock
datasets, while dry-run may preserve them with an explicit warning.

Use:

```python
from genkai.workflow.store import load_manifest

manifest = load_manifest(run_root)
for artifact in manifest.artifacts:
    print(artifact.artifact_id, artifact.artifact_type, artifact.evidence_level)
```

Incompatible artifact changes increment the schema major version. Consumers
declare requirements such as `dataset@1`; the workflow validator rejects
missing producers, wrong artifact types, incompatible majors, and cycles before
external execution.
