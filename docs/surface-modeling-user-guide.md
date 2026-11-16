# Genkai 表面建模使用手册

本手册面向想用 Genkai 生成表面结构、但不参与代码开发的使用者。所有操作都通过一个命令
`genkai-surface` 和一个 YAML 任务文件完成，不需要了解各建模脚本的内部参数。

## 1. 能做什么

| 方法 | 用途 | 必须提供 |
| --- | --- | --- |
| `slab` | 从块体晶体切出表面 slab | 块体结构 |
| `vacancy` | 在含氧 slab 表面去掉 O 原子（氧空位） | slab |
| `adsorbate` | 把气体或有机分子放到表面位点上，生成不同覆盖度 | slab、分子、位点元素 |
| `cluster` | 构建 fcc/hcp/bcc 金属团簇并放到表面 | slab、金属元素、团簇大小 |
| `sam` | SAM 自组装单分子层：膦酸、羧酸、硫醇按选定结合方式锚定 | 块体或 slab、分子、结合方式、分子数 |
| `ald` | ALD 非晶覆盖层：全覆盖成膜，或部分覆盖成岛 | 块体或 slab、非晶块体、覆盖方式 |
| `amorphous_slab` | 从非晶块体切出纯非晶表面 | 非晶块体、厚度 |

用户输入的结构默认是 CIF，也可以用 POSCAR、XYZ、extxyz 等 ASE 能读取的格式。

**目前只生成结构，不计算能量。** 生成的是未弛豫的几何结构，用作后续 DFT 或 MLIP 计算的初始结构。
计算器固定为 `none`。空位和吸附方法会顺带输出能量表格和图，其中的能量是模拟值，没有物理意义。

下面这些功能暂未开放：

- SAM 能量搜索（`sam_search`）；
- 非晶表面能排序和界面搜索（`amorphous_screen`）；
- 团簇或非晶岛的负载位置搜索（`cluster_search`）；
- 从 Materials Project 下载结构。

前三项需要 UMA，要等服务器上的基准测试完成后再开放。Materials Project 需要联网和 API 密钥，
请先自己下载 CIF 文件，再作为 `bulk` 输入。

## 2. 安装

需要 Python 3.11 或更高版本（推荐 3.12）。下面使用的是只含建模部分的 `SAGE` 分支。

### 2.1 获取代码并安装（Linux、WSL、超算登录节点）

```bash
git clone -b SAGE --single-branch https://github.com/alekseyevich180/Genkai_Agent.git SAGE
cd SAGE
./install.sh
source .venv/bin/activate
```

`install.sh` 会在仓库内创建 `.venv`，安装建模依赖和测试工具，然后检查 `genkai-surface` 并跑一组快速测试。
有 `uv` 时用 `uv`，没有时用 `pip`。常用选项：

| 选项 | 作用 |
| --- | --- |
| `--mlip` | 另外安装 fairchem-core（UMA），用于 MLIP 测试 |
| `--torch-index-url URL` | 先从指定源安装与服务器 CUDA 匹配的 torch |
| `--system-site-packages` | 让环境能看到集群模块提供的包（如预装的 torch） |
| `--python PY` | 指定 Python 解释器 |
| `--dry-run` | 只显示将要执行的命令 |

全部选项见 `./install.sh --help`。

### 2.2 Windows 电脑

`install.sh` 也可以在 Git Bash 里运行。没有 Git Bash 时，在 PowerShell 中手动安装：

```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[test]"
```

### 2.3 确认安装成功

```bash
genkai-surface methods
```

如果提示找不到 `genkai-surface`，先确认已经激活 `.venv`。下面的写法完全等价，任何时候都可以用：

```bash
python -m genkai.modeling.surface.jobs methods
```

## 3. 三步上手

```bash
# 1. 生成模板：带中文注释，列出该方法的全部参数
genkai-surface template sam -o my_sam.yaml

# 2. 用文本编辑器打开 my_sam.yaml，把 <...> 换成自己的文件，再检查一遍（不会运行）
genkai-surface check my_sam.yaml

# 3. 运行
genkai-surface run my_sam.yaml
```

运行结束后，屏幕上会显示每个结构文件的检查结果，输出都在任务文件里 `output` 指定的目录中。

可以先跑仓库自带的示例，看看效果（每个示例在普通电脑上需要几秒到半分钟）：

```bash
genkai-surface run examples/surface_jobs/05_sam_sno2_butanoic.yaml
genkai-surface run examples/surface_jobs/*.yaml        # 全部示例（Windows 上也可以这样写）
```

示例的说明见 [examples/surface_jobs/README.md](../examples/surface_jobs/README.md)。

## 4. 任务文件写法

### 4.1 基本结构

```yaml
method: sam                     # 建模方法
output: runs/sam_sno2           # 输出目录（可以不写，默认是 runs/<任务文件名>）
description: SnO2(110) 上的丁酸 SAM   # 备注，会记进 manifest.json（可以不写）

bulk: inputs/SnO2.cif
molecule: inputs/butanoic_acid.xyz
binding_mode: monodentate
counts: [1, 2]
```

用 `genkai-surface methods <方法名>` 查看某个方法的全部参数、默认值和组合规则。

### 4.2 规则

- **相对路径以任务文件所在目录为准**，与在哪个目录下运行命令无关。
- **Windows 路径**请用正斜杠：`D:/data/SnO2.cif`；或用单引号：`'D:\data\SnO2.cif'`。
  不要用双引号括反斜杠路径，YAML 会把 `\U`、`\n` 当成转义字符。
- 路径里有空格时，用单引号括起来：`surface: 'inputs/CeO2 (1 1 1).cif'`。
- **晶面**写成带引号的字符串（`"110"`、`"0001"`、`"1-10"`）或列表（`[1, 1, 0]`）。
- 多个数可以写成列表 `[1, 2]`，也可以写成 `1, 2`。
- 行首加 `#` 表示注释；不写的参数使用默认值。
- 文件请保存为 UTF-8 编码。
- `calculator`、`device`、`uma_model`、`formula` 等涉及能量计算或联网的参数不能写，写了会报错并说明原因。

### 4.3 一个文件写多个任务，或把任务串联起来

```yaml
jobs:
  - method: amorphous_slab
    output: runs/chain/amorphous
    amorphous: inputs/a-SnO2.vasp
    thickness: 8

  - method: sam
    output: runs/chain/sam
    surface: runs/chain/amorphous/amorphous_slab_000.extxyz   # 用上一个任务的输出
    molecule: inputs/butanoic_acid.xyz
    binding_mode: bidentate
    counts: [1]
```

任务按顺序运行。`check` 时第二个任务的输入还不存在，会提示“会由前面的任务生成”。
同一个文件里的某个任务失败后，后面的任务会被跳过。

## 5. 各方法要点

- **slab**：不写 `facet` 时，按内置稳定晶面表选择。表里有 CeO2、TiO2、SnO2、RuO2、IrO2，
  以及 fcc、bcc、hcp 金属，岩盐、萤石、金红石结构。表里没有的材料会停下并提示，请写 `facet`。
  晶面指数默认相对常规晶胞。
- **vacancy**：只处理 O 空位。`z_frac_min`/`z_frac_max` 按整个晶胞高度的分数坐标计算；
  slab 放在晶胞底部时，表层原子的 z 通常远小于 1。
- **adsorbate**：`site_symbols` 是吸附位点的表面元素，如 `Ce`。放置多个分子时，程序不检查分子之间的重叠，
  大分子在小晶胞上可能出现原子过近，检查结果会标为 WARN，请换大晶胞或减少分子数。
- **cluster**：`cluster_element` 和 `cluster_bulk_file` 至少写一个；大小用 `cluster_atoms`、`cluster_layers`、
  `cluster_radius` 三选一。团簇按几何规则放置，没有做优化。
- **sam**：`binding_mode` 由使用者选择。膦酸可选 monodentate、bidentate、tridentate；羧酸可选 monodentate、
  bidentate；硫醇可选 top、bridge、hollow、fcc、hcp。酸性 H 默认这样处理：在含 O 的表面转移成表面 OH，
  在金属表面直接去掉。分子里有多个锚定基团时，需要写 `anchor_kind`。
- **ald**：`coverage: full` 时必须写 `thickness`（膜厚，Å）。能晶格匹配时整体应变成膜，不能时切割并修复接缝；
  `film_fit` 可以指定方式。`coverage: partial` 时用 `island_atoms` 或 `island_radius` 控制岛的大小；
  不写 `facet` 时，岛放在最稳定晶面上。
- **amorphous_slab**：只保留不需要删除原子的切割位置，以保持化学计量；`samples` 控制切出几个不同的表面。

## 6. 看结果

每个任务的输出目录里有：

| 文件 | 内容 |
| --- | --- |
| 主结构文件（见下表） | 生成的结构 |
| `exports/` | 额外导出的 CIF 或 POSCAR，便于用 VESTA 查看或作为 DFT 输入（sam、ald、amorphous_slab） |
| `manifest.json` | 运行记录：输入文件和它们的 sha256、参数、软件版本、每个结构的检查结果 |
| `job_resolved.yaml` | 实际运行的任务（路径已展开），可用来复现 |
| `run.log` | 方法本身的完整输出；出错时先看这里 |

| 方法 | 主结构文件 |
| --- | --- |
| slab | `slab.extxyz`（另有 POSCAR 格式的 `slab.vasp`） |
| vacancy、adsorbate | `structures/*.cif` |
| cluster | `*_on_surface.cif` |
| sam | `sam_structures.extxyz` |
| ald | `ald_structures.extxyz` |
| amorphous_slab | `amorphous_slab_structures.extxyz` |

extxyz 文件可以包含多个结构（多帧），并保留固定原子的信息，可以用 OVITO 或 `ase gui 文件名` 打开。
CIF 不保存固定原子信息。

空位和吸附方法的输出目录里还有一些文件名带 stable、relaxed、best 的 CIF（如 `stable_vacancy_structure.cif`、
`surface_relaxed.cif`、`single_adsorbate_best.cif`），以及能量表格和图。它们来自这两个脚本的能量计算流程。
目前计算器固定为 `none`，这些文件要么没有弛豫，要么是按模拟能量挑出来的，文件名不代表真实结果。
请只使用 `structures/` 里的结构。

屏幕上的检查结果：

- **PASS**：结构可以读取、没有原子过近、有真空层，extxyz 文件里有固定原子。
- **WARN**：结构生成了，但有需要人工检查的问题。
  - 原子过近：最小接触比小于 0.6，即原子间距小于两原子共价半径之和的 0.6 倍。
  - 真空层小于 5 Å。
  - extxyz 里没有固定原子。
- **FAIL**：方法运行出错或没有生成结构。屏幕上会显示最后几行输出，完整内容见 `run.log`。
- **SKIP**：同一任务文件里前面的任务失败，这个任务没有运行。

## 7. 在超算上使用

安装方法与第 2 节相同（Linux）。结构生成只用 CPU，每个任务通常只需要几秒到一分钟，
一般可以直接在登录节点运行：

```bash
source .venv/bin/activate
genkai-surface run my_job.yaml
```

如果所在中心不允许在登录节点运行程序，可以通过 PJM 提交。下面是模板，`<...>` 按中心的说明填写。
这份模板还没有在超算上实际提交验证过。

```bash
#!/usr/bin/env bash
#PJM -N surface_jobs
#PJM -L rscgrp=<CPU 资源组>
#PJM -L node=1
#PJM -L elapse=1:00:00
#PJM -j
#PJM -S

set -euo pipefail
cd "${PJM_O_WORKDIR}"
source <仓库路径>/.venv/bin/activate
genkai-surface run --quiet my_job.yaml
```

用 `pjsub 脚本名.sh` 提交。`--quiet` 只显示检查结果，方法本身的输出写进各任务的 `run.log`。

## 8. 常见问题

| 现象 | 处理 |
| --- | --- |
| 找不到 `genkai-surface` | 先激活 `.venv`；也可以用 `python -m genkai.modeling.surface.jobs` |
| `YAML 格式错误` | 检查缩进和冒号后的空格；Windows 路径用 `/` 或单引号 |
| `xxx 没有参数 yyy，是不是 zzz？` | 参数名拼错了；用 `genkai-surface methods <方法名>` 查看全部参数 |
| `calculator 不能设置` | 目前只开放结构生成，删掉这一行 |
| `输出目录已有内容` | 换一个 `output`，或删除旧目录，或加 `--overwrite`（旧文件不会被删除；本次没有更新的旧结构文件不计入检查和 `manifest.json`，但仍留在目录里） |
| slab 不写 facet 时报错要求审核 | 材料不在内置稳定晶面表里，请写 `facet` |
| 吸附结构标为 WARN（原子过近） | 多个大分子挤在小晶胞里；换大晶胞（slab 的 `min_lateral_size` 或 `repeat_xy`）或减少分子数 |
| 中文注释显示乱码或读取失败 | 把任务文件另存为 UTF-8 编码 |

## 9. 反馈问题

请把以下内容发给维护者：

- 任务文件；
- 输出目录里的 `job_resolved.yaml`、`run.log`、`manifest.json`；
- `genkai-surface run` 在屏幕上的输出。

如果输入结构不方便公开，可以只发这几个文本文件。
