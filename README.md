# SAGE：气体传感研究的自动化原子级表面建模

SAGE（An AI agent for automated atomistic surface modeling in gas sensor research）分支只保留了
Genkai 中的表面建模部分：

- 切面、氧空位、分子吸附、金属团簇、SAM、ALD 非晶覆盖层、纯非晶表面，共 7 种结构生成方法；
- MLIP 筛选层：SAM 锚定搜索、非晶表面与界面筛选、团簇或岛的负载位置搜索，通过 FAIRChem 调用 UMA。

Agent 运行时、Web 界面、论文抽取（LLM）、MLIP 训练适配器和其他 Skill 不在这个分支上，需要时请到 `main` 分支。
这个分支用来在服务器上加入和运行 MLIP 测试。

## 安装

需要 Python 3.11 或更高版本（推荐 3.12）。

```bash
git clone -b SAGE --single-branch https://github.com/alekseyevich180/Genkai_Agent.git SAGE
cd SAGE

./install.sh                 # 结构生成和测试（模拟计算器，不需要 GPU）
./install.sh --mlip          # 另外安装 fairchem-core（UMA），用于 MLIP 测试
./install.sh --mlip --torch-index-url https://download.pytorch.org/whl/cu121   # 指定与服务器 CUDA 匹配的 torch
./install.sh --help          # 全部选项
```

脚本在仓库内创建 `.venv`，以可编辑方式安装当前检出的代码，所以 `git pull` 后不用重新安装；
依赖有变化时再运行一次即可。安装前会检查 Python 版本，安装后会检查 `genkai-surface` 命令、
运行一组快速测试；加 `--mlip` 时还会列出 UMA 任务头和 CUDA 是否可用，但不会下载或加载模型。

```bash
source .venv/bin/activate
```

## 使用

```bash
genkai-surface methods                       # 可用的建模方法
genkai-surface template sam -o my_sam.yaml   # 生成任务文件模板
genkai-surface check my_sam.yaml             # 只检查
genkai-surface run my_sam.yaml               # 运行
genkai-surface run examples/surface_jobs/*.yaml   # 自带示例
```

任务文件写法、输出说明和常见问题见 [表面建模使用手册](docs/surface-modeling-user-guide.md)。
`genkai-surface` 只做结构生成（计算器固定为 none）。MLIP 筛选目前通过各方法自己的命令行运行，
见 [SKILL.md](agents/Agent/skills/surface-modeling/SKILL.md) 的 “MLIP Screening Layer” 一节。

## 测试

```bash
python -m pytest -q                          # 单元、契约和集成测试（不需要网络和 GPU）
python scripts/run_modeling_smoke.py         # 用仓库里的结构逐一调用全部方法（模拟计算器，约 5 分钟）
python scripts/run_modeling_smoke.py --profile server --device cuda --uma-task <任务头>   # 改用 UMA
```

运行 UMA 前请注意：

- 只在获准进行真实计算的服务器上运行；
- 先确定 UMA 任务头。可用的任务头取决于所装的 fairchem 版本，例如 fairchem 2.7.1 有 omol、omat、
  odac、oc20、oc25、omc，没有 oc22；
- 第一次运行会从 Hugging Face 下载模型，通常需要先接受模型许可，并设置 `HF_TOKEN`
  （或运行 `hf auth login`，旧版为 `huggingface-cli login`）；
- 模拟计算器（`calculator=none`）给出的能量和排序没有物理意义，只用来确认流程能走通。

## 目录

| 路径 | 内容 |
| --- | --- |
| `src/genkai/modeling/surface/` | 建模方法、MLIP 筛选层、`genkai-surface`（`jobs.py`） |
| `src/genkai/modeling/` | PToModel 建模计划（mapping、ptomodel、checklist、schema） |
| `src/genkai/contracts/`、`src/genkai/workflow/` | artifact 与运行清单（`manifest.json`）契约 |
| `src/genkai/literature/surface/` | 只保留建模用到的词表和读取已保存抽取结果的函数 |
| `agents/Agent/skills/surface-modeling/` | 各方法的薄入口脚本、Skill 说明和示例结构 |
| `examples/surface_jobs/` | `genkai-surface` 示例任务文件 |
| `scripts/run_modeling_smoke.py` | 建模冒烟测试 |
| `tests/` | 测试和测试用结构 |
| `AGENTS.md` | 在这个分支上工作的规则 |
