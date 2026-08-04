
# Genkai: An agent for materials, chemistry, and simulation.

<p align="center">
  <img src="https://raw.githubusercontent.com/alekseyevich180/Genkai_Agent/main/genkai-logo.png" alt="Genkai logo theme" width="400">
</p>


## Agent

Agent is a **skill-based, agentic platform** for computational material science tasks, with a focus on Machine Learning Force Field (MLFF) generation and application. It would evolve with users by experience accumulation and creation of new skills.

This workspace now includes a surface-oriented modeling skill at `agents/Agent/skills/surface-modeling/`. It covers oxide surface vacancy landscapes, adsorbate coverage landscapes, and metal nanocluster placement on surfaces, with fast mock-calculator checks and optional UMA/FAIRChem workflows for production relaxation.

MLIP workflows are exposed as three separate built-in skills with explicit
roles:

- `agents/Agent/skills/mace/`: pretrained MACE/MACE-MP energy, force and
  relaxation calculations;
- `agents/Agent/skills/deepmd/`: DeepMD dataset preparation, training,
  checkpoint continuation, freezing, compression and testing;
- `agents/Agent/skills/uma/`: UMA single-task fine-tuning, resume and
  fine-tuned-model evaluation.

The UMA preparation gate audits ASE-readable energy/force/stress labels and a
retained test split, rejects severe atomic overlaps and cross-split leakage,
creates train/validation ASE-LMDB, checks converter failure logs, reads the
generated LMDB back, and composes the version-matched
`fairchem-core 2.21.0` Hydra configuration before training handoff. Data,
reports, configurations, checkpoints and logs remain in the caller's project.

### Library-first workflow core

The stable scientific workflow API now lives under `src/genkai/`. It provides
versioned artifact/provenance contracts, atomic run manifests, artifact-aware
DAG validation, surface workflow facades, VASP preparation/result boundaries,
ASE dataset audits, and separate MACE, DeepMD, and UMA adapters. Existing
Agent entrypoints now call this library. The removed `paperread.surface`
literature imports and module CLI are not compatibility targets in this
evolution workspace. Task 12's PToModel mapping, checklist, canonical
surface-task schema, and surface structure-generation algorithms now live under
`src/genkai/modeling/`; the original Skill paths remain thin compatibility
wrappers.

Initialize and inspect an offline reference run:

```bash
genkai-workflow init runs/demo \
  --relations tests/fixtures/paper_to_mlip/minimal_surface_relations.jsonl \
  --mock-labels tests/fixtures/paper_to_mlip/mock_labels.extxyz \
  --base-model-uri file:///path/to/read-only/uma-checkpoint.pt
genkai-workflow inspect --run-root runs/demo
genkai-workflow preflight --run-root runs/demo --target uma --mode dry-run
```

This workflow never treats the fixture as DFT evidence: UMA production
preflight rejects its mock labels, while dry-run records a warning and starts
no VASP, GPU, PJM, DeepMD, MACE, or UMA process. See
[`docs/artifact-contracts.md`](docs/artifact-contracts.md) and
[`docs/skill-development.md`](docs/skill-development.md).

The maintained paper-reading implementation lives under
`src/genkai/literature/surface/`. It can ingest surface-research PDFs or JSON
text, extract surface materials, reaction/material parameters, adsorbates,
active sites, defects, single atoms, clusters, and modeling keywords, then
hand structured relations to the workflow layer.

Extracted useful or unknown information is accumulated by inorganic material
class under
`src/genkai/literature/surface/experience/material_classes/`, such as
`carbon_materials`, `single_atom_catalysts`, `oxides`, and
`supported_catalysts`, so repeated paper-reading results can improve later
schema, prompt, planner, and skill updates.

### Paperread surface workflow

For surface-reaction papers, use the unified `paperread` skill rather than the
older standalone `ReactionSeek` or `NERRE` entrypoints. The maintained path is:

```text
PDF or JSON paper text
-> genkai.literature.surface extraction
-> condition table, time table, surface relations, summary
-> genkai.workflows.surface_paper artifact initialization and modeling plan
-> material-class experience store
-> skill-side unknown-term store and surface parameter registry
```

Run a single paper:

```bash
genkai-workflow surface run /path/to/paper.pdf \
  --run-root paperread_output \
  --input-format pdf \
  --collect-experience
```

Important paperread outputs:

- `*_table.csv`: reaction and material condition table.
- `*_time.csv`: normalized time values.
- `*_surface_relations.jsonl`: structured materials, surfaces, adsorbates,
  active sites, defects, single atoms, clusters, reactions, and modeling cues.
- `*_summary.txt`: short human-readable extraction summary.
- `manifest.json` and artifact payloads: extraction, modeling-plan, and
  structure-candidate provenance initialized by the workflow layer.
- `src/genkai/literature/surface/experience/material_classes/*.json`: canonical reusable
  material-class keyword store.
- `agents/Agent/skills/paperread/experience/surface_parameter_registry.{json,md}`:
  reusable vocabulary built from the canonical experience store.
- `agents/Agent/skills/paperread/experience/unrecognized_surface_terms.jsonl`:
  unresolved surface-paper terms that may require ontology or workflow updates.

For lower-level batch PDF extraction, the Agent paperread skill can retain
intermediates without invoking the workflow-level modeling bridge:

```bash
python agents/Agent/skills/paperread/scripts/paperread_tools.py surface-pipeline \
  --input /path/to/paper.pdf \
  --output-dir tests/paperread_papers2_experience \
  --keep-intermediate \
  --collect-experience
```

`--keep-intermediate` preserves `*_text.txt`, `*_sections.json`,
`*_conditions_input.json`, and `*_relations_input.json`. These files are the
resume point when API calls fail or rate limits interrupt extraction; continue
from the generated JSON rather than reparsing the PDF.

Current paperread state from `work_logs/2026-07-08.md`:



## Quick start
### Linux 安装

以下安装流程适用于 Linux，并要求 Python 3.12 或更高版本：

```bash
# 如果尚未安装 uv，请先安装
pipx install uv

# 创建并激活项目虚拟环境
uv venv .venv --python 3.12
source .venv/bin/activate

# 以可编辑模式安装 Agent，并安装测试工具
uv pip install -e .
uv pip install pytest

# 可选：从 GitHub 安装最新 pymatgen
uv pip install "git+https://github.com/materialsproject/pymatgen.git"

# 安装前端依赖
cd web/vite-frontend
npm install
cd ../..
```

### pymatgen 简单调用

激活项目虚拟环境后可以直接在 Python 中使用：

```bash
source .venv/bin/activate
python - <<'PY'
from pymatgen.core import Lattice, Structure

structure = Structure(
    Lattice.cubic(3.5),
    ["Si"],
    [[0, 0, 0]],
)

print(structure.formula)
print(structure.lattice.a)
PY
```

如果需要读取 CIF/POSCAR 等结构文件：

```python
from pymatgen.core import Structure

structure = Structure.from_file("structure.cif")
print(structure.composition.reduced_formula)
```

### Configuration

After installation, tell the CLI where the project root lives:

```bash
# Run from the repo directory
agent init .

# Or specify an absolute path
agent init /path/to/PFD-Agent
```

This writes `~/.agent/config.yaml` with the `project_root` path, so the
CLI can locate the `agents/` directory even when installed into site-packages.
You can also set the `AGENT` environment variable instead.

## Vite Frontend Requirements

This project includes a frontend interface. The frontend depends on `node`, `npm`, and the local `vite` dev server.

### Install NVM

Use NVM to manage Node.js.

```bash
# Install nvm
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash
source ~/.bashrc

# Verify installation:
nvm --version
```

### Install Node.js
```bash
nvm install 22
nvm use 22
nvm alias default 22
```

Verify the installation
```bash
node -v
npm -v
```

### Install frontend dependencies

```bash
cd web/vite-frontend
npm install
npm run dev
```

### Recommended Workflow: WSL + uv for Virtual Environment Deployment

We highly recommend using WSL (Windows Subsystem for Linux) with uv to deploy local development virtual environments. WSL provides a native Linux environment seamlessly integrated with Windows, enabling access to Linux tools. As a fast, lightweight Python package manager, uv creates isolated environments to avoid dependency conflicts, ideal for Python applications like Streamlit.

#### Why Use pipx for uv in WSL

In WSL, system Python is managed by apt and is a core system component. PEP 668 prohibits direct pip installation to avoid breaking system dependencies. Pipx is ideal for tools like uv: it creates isolated virtual environments for global access without polluting system Python.

#### Solution: Install uv Using pipx

As a command-line tool, uv can be installed via pipx, which creates an independent virtual environment for global use. Run these commands in the WSL terminal:

```bash
# 1. Install pipx
sudo apt update && sudo apt install pipx -y

# 2. Initialize pipx (add to system PATH)
pipx ensurepath

# 3. Restart terminal, then install uv
pipx install uv
```

### Running agent networks
#### Setting environments
Before the first run, create the `agents/Agent/.env` file and configure your model API credentials (additional environment variables may be required for some functionalities).

```bash
touch agents/Agent/.env
```

An example content of `.env`:

```env
LLM_MODEL= "MODEL_TYPE"
GRAPH_AGENT_MODEL="MODEL_TYPE"             # optional; defaults to LLM_MODEL
REVIEW_AGENT_MODEL="MODEL_TYPE"            # optional; defaults to GRAPH_AGENT_MODEL
LLM_API_KEY="API_KEYS"
LLM_BASE_URL="BASE_URL"
KDG_DB_PATH="agents/Agent/.adk/know_do_graph.db"
EMBEDDING_MODEL="EMBEDDING_MODEL_TYPE"
AGENT_AUTO_REVIEW=1
AGENT_REVIEW_TRIGGER_THRESHOLD=20
AGENT_REVIEW_BATCH_SIZE=5
AGENT_REVIEW_STRATEGY=auto             # auto, seed, or global

# SKILL_RELATED_ENV
CGCNN_ROOT=user/cgcnn                         # CGCNN project directory
MATTERGEN_ENV=user/../.mattergen              # MATTERGEN virtual environment
TAVILY_API_KEY=""
BOHRIUM_MAT_IMAGE=""                          # MATTERGEN and MATTERSIM IMAGE
BOHRIUM_MAT_MACHINE=""                        # MATTERGEN and MATTERSIM IMAGE
eval_reference="user/../reference_MP2020correction.gz"
mattersim_model="user/../mattersim-v1.0.0-5M.pth"
mattergen_model="user/../mattergen/checkpoints"
BOHRIUM_VASP_IMAGE=""
BOHRIUM_VASP_MACHINE=""
...
```

If you prefer different LLM models for sub-agents, you can override the default setting at the `.env` file within sub-agents directories. 

#### 启动 Web UI（推荐）

Web UI 提供执行图可视化、产物上传与下载、材料结构显示和科学绘图功能。使用以下脚本可以同时启动 ADK API Server、FastAPI 中间层和 Vite 前端：

```bash
# 激活 .venv 后，在仓库根目录执行
bash start/start_agent.sh
```

该脚本会启动：

- **ADK API Server**：`http://localhost:8000`
- **FastAPI 中间层**：`http://localhost:8001`
- **Vite 前端**：`http://localhost:5173`

日志写入 `logs/{api-server,web-main,vite}.log`。按 `Ctrl+C` 可以停止全部服务。

如果服务启动失败，可以通过以下命令查看对应日志：

```bash
tail -f logs/api-server.log
tail -f logs/web-main.log
tail -f logs/vite.log
```

> 开发模式不需要预先构建前端；Vite 开发服务器会直接运行并提供热更新。

![The web UI for Agent]()

#### Non-interactive CLI mode

Run the agent on a single prompt without starting any server:

```bash
# Inline prompt
agent run -p "Build a silicon FCC structure"

# Prompt from a file
agent run -f prompt.txt

# Save the answer to a file
agent run -p "Build a silicon FCC structure" -o result.txt

# Full structured JSON output (includes turn count, duration, etc.)
agent run -p "Build a silicon FCC structure" --output-format json -o result.json

# Override the workspace directory
agent run --workspace /data/my_workspace -p "Build a silicon FCC structure"
# or via environment variable
MATCLAW_WORKSPACE=/data/my_workspace agent run -p "Build a silicon FCC structure"
```

Each run creates a session directory under `<workspace>/sessions/<session-id>/` where any files produced by the agent are saved.

#### Default adk web server (old style)

```bash
agent web
```
This sets up the Agent network through the default `adk web` server. You can tune the LLM model and communication settings for the agents.

The default agent workspace is located at `agents/Agent/.workspace`, where skills, memory, etc., are stored.

### 自动化测试

激活虚拟环境，并在仓库根目录执行后续命令：

```bash
source .venv/bin/activate
```

运行与 GitHub Actions 相同的模块导入完整性测试：

```bash
python -m pytest tests/test_agent.py -v
```

运行 Know-Do Graph 的记忆、提取和审核流程测试：

```bash
python -m pytest \
  tests/test_kdg_memory.py \
  tests/test_kdg_extractor.py \
  tests/test_kdg_review_pipeline.py \
  tests/test_kdg_auto_review.py \
  -v
```

运行全部本地测试：

```bash
python -m pytest tests -v
```

`tests/test_structure_builder.py` 目前依赖已经不存在的
`agent.tools.structure_builder` 模块。因此，在恢复该模块或删除此测试前，
完整测试套件无法全部通过。当前 `.github/workflows/test.yml` 中的 GitHub
Actions 仅在推送和拉取请求时运行 `tests/test_agent.py`。

## Skills
Agent follows a modular design principle: skills are text files that define metadata, procedures and workflows. Some skills may require specialized tools (configured by `$PROJECT/agents/Agent/tools.py`), and some of them, e.g. tools for DFT calculations, may be hosted on MCP servers.

> The default domain-based computational materials datasets is located at `database/domain_datasets.tar.gz`, which should be extracted for database skill usage. (See `tools/database/README.md`)

> Check the `README.md` in `skills/$SKILL` if you really wanna use them. 


> **Note — transitioning from MCP servers to skills:** Agent is progressively moving tool logic out of dedicated MCP servers and into self-contained skills. A skill bundles its own workflow instructions, helper scripts, and configuration alongside the `.md` file, so it can be run with only a general-purpose shell/Python tool rather than a running server process. If a capability you previously used via an MCP server is no longer listed under `tools/`, check `agents/Agent/skills/` — it may have been migrated to a skill. MCP servers are retained only for tools that genuinely require a persistent service (e.g. a remote job scheduler or a database backend).


###  Server setup (Optional)
For example, to set up a `mcp` server for `ABACUS` DFT software, `uv run` the script: 

```bash
cd tools/abacus
uv sync 

uv run server.py --port 50001
```
 You may need to set environment variables specific to the mcp server at `tools/$TOOLNAME/.env`, which can be referenced in `tools/$TOOLNAME/README.md`

### Customize skills

Skills are Markdown files with a YAML frontmatter block (declaring `name`, `description`, `tools`, and `dependent_skills`) followed by a plain-text instruction body. The active loader discovers any workspace directory that contains a `SKILL.md` file, including nested directories such as `skills/mattergen/mattergen_generation/SKILL.md`. Agent loads skills from two locations in order:

1. **Built-in skills** — shipped with the package under `agents/Agent/skills/`. Each skill lives in a directory containing a `SKILL.md` file.
2. **Workspace overlay** — your personal skills under `$MATCLAW_WORKSPACE/skills/` (defaults to `.workspace/` in the project root). Any skill here with the same name overrides the built-in version.

To customize a skill manually, copy its skill directory into your workspace `skills/` directory and edit the contained `SKILL.md`. To add a new skill, create a new `skills/<name>/SKILL.md` file following the same frontmatter format.

The agent can also create and update skills on its own. During a session, the thinking agent can call built-in tools to scaffold a new skill file, write updated content to an existing one, or list what skills are currently available — letting the system accumulate knowledge automatically over time.

## Know-Do Graph

Agent uses `know-do-graph` for both durable knowledge and working memory:

- **Know-Do Graph** stores curated capabilities, procedures, workflows, and
  distilled heuristics in `agents/Agent/.adk/know_do_graph.db` by default.
- **MemGraph** stores frequently updated agent observations as
  `EntryType.memory` nodes and normal graph edges in the same SQLite database.

Skills and guides are seeded as durable entries. Agent writes first land in
MemGraph; repeated successful observations are later distilled into validated
Know-Do heuristics and linked to the capabilities they improve. Existing
`skill_graph.db`, `memory_graph.db`, old JSON traces, and `MEMORY.md` data can be migrated
idempotently. See [manual.md](manual.md).

## Graph-Based Planning

When given a goal, the thinking agent produces an **execution graph** — a directed acyclic graph (DAG) where each node is a discrete action and each edge encodes a dependency.

```
step_download_data ──► step_relax ──► step_postprocess
                   └──► step_static ─►
```

Key properties:

- **Nodes** carry a `node_id`, human-readable `label`, natural-language `action` description, and a list of `suggested_skills`.
- **Edges** are `[predecessor_id, successor_id]` pairs. A node cannot start until all its predecessors have succeeded.
- **Parallel execution**: nodes with no unresolved dependencies are dispatched concurrently in a single turn.
- **Failure propagation**: if a node fails, all transitive dependents are marked `blocked` automatically.

The agent validates the graph for cycles before presenting it to the user, then waits for explicit confirmation before handing it off to the execution agent.
