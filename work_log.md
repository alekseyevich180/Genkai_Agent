# 当前任务 Checkpoint：paperread 外部库接入

更新时间：2026-06-29

本次任务目标：

- 将 `ReactionSeek` 和 `NERRE` 两个论文/文献读取相关项目接入当前 Genkai Agent 项目。
- 安装位置统一放在 `paperread/`，不是 `external/`。
- 删除两个项目和源 GitHub 仓库之间的 branch/remote 关系，方便后续直接修改源码。
- 两个项目的 API 调用复用当前 Agent 项目的原始 API 配置。

当前目录结构：

```text
paperread/
  ReactionSeek/
  NERRE/
  genkai_api_config.py
  requirements.txt
  README.md
```

来源记录：

```text
paperread/ReactionSeek/LOCAL_ORIGIN.md
paperread/NERRE/LOCAL_ORIGIN.md
```

两个项目内部的 `.git` 目录已经删除。下次可用以下命令确认：

```bash
find paperread -name .git -type d -print
```

正常情况下不应输出任何内容。

API 环境参数位置：

```text
agents/Agent/.env
```

这两个库不单独维护 API key。`paperread/genkai_api_config.py` 会读取同一份 `agents/Agent/.env`：

```env
LLM_MODEL="github/openai/gpt-4.1"
GRAPH_AGENT_MODEL="github/openai/gpt-4.1"
LLM_API_KEY="你的_GitHub_Token"
LLM_BASE_URL="https://models.github.ai/inference"
```

如果使用 GitHub Models 免费 API，GitHub token 需要 `models:read` 权限。`LLM_BASE_URL` 填：

```env
LLM_BASE_URL="https://models.github.ai/inference"
```

已做的兼容改造：

- 新增 `paperread/genkai_api_config.py`，统一读取 `agents/Agent/.env`。
- 为旧 OpenAI SDK 写法提供兼容：
  - `openai.ChatCompletion.create(...)`
  - `openai.Completion.create(...)`
- 已接入主要调用文件：
  - `paperread/ReactionSeek/ReactionSeek/reaction_extract/extract_gpt.py`
  - `paperread/ReactionSeek/ReactionSeek/standardize/time_standardlize.py`
  - `paperread/ReactionSeek/ReactionSeek/standardize/name_to_smiles.py`
  - `paperread/NERRE/doping/step2_train_predict.py`
  - `paperread/NERRE/doping/step1_annotate.py`
  - `paperread/NERRE/general_and_mofs/utils.py`
  - `paperread/NERRE/general_and_mofs/data/predict.py`

依赖安装情况：

- 当前 `.venv` 已安装 paperread 相关依赖。
- 上游项目的 OpenAI 依赖版本互相冲突：
  - ReactionSeek 要 `openai==1.76`
  - NERRE 要 `openai==0.27.7`
- 当前项目保留已有 OpenAI SDK，不降级，避免破坏 Agent/ADK/LiteLLM。
- `ChemDataExtractor==1.3.0` 的原始依赖 `DAWG` 在 Python 3.12 下编译失败，已安装 `DAWG2` 作为兼容替代，它提供可导入的 `dawg` 模块。
- `pip check` 可能仍提示 `chemdataextractor 1.3.0 requires dawg`，这是包元数据层面的提示；实际 `import dawg` 已通过。

已验证命令：

```bash
.venv/bin/python - <<'PY'
import sys
sys.path.insert(0, 'paperread/ReactionSeek/ReactionSeek/reaction_extract')
import extract_gpt
sys.path.insert(0, 'paperread/ReactionSeek/ReactionSeek/standardize')
import time_standardlize, name_to_smiles
print('ReactionSeek imports ok')
PY
```

```bash
/home/pj24001724/ku40000345/wu/Genkai_Agent/.venv/bin/python - <<'PY'
import step2_train_predict
print('NERRE doping import ok')
PY
```

运行目录：

```text
/home/pj24001724/ku40000345/wu/Genkai_Agent/paperread/NERRE/doping
```

```bash
/home/pj24001724/ku40000345/wu/Genkai_Agent/.venv/bin/python - <<'PY'
import utils
print('NERRE general utils import ok')
PY
```

运行目录：

```text
/home/pj24001724/ku40000345/wu/Genkai_Agent/paperread/NERRE/general_and_mofs
```

注意事项：

- `paperread/` 下有部分上游示例数据很大，`rg` 搜索时输出可能非常长，建议限制路径或使用 `--glob '*.py'`。
- `NERRE/doping/step1_annotate.py` 在 Python 3.12 下有少量 invalid escape sequence 警告，不影响当前导入。
- 如果后续要让 Agent 自动调用这两个库，下一步应在 `agents/Agent/skills/` 下新增 paperread 相关 skill，并把调用脚本封装成稳定入口。

## paperread 两个项目对比：面向表面研究的可用性整理

更新时间：2026-06-29

本节目标：

- 比较 `ReactionSeek` 与 `NERRE` 的抽取目标、输入输出和适用场景。
- 筛出能够直接或经过轻度改造后服务于表面研究的部分。
- 为后续把表面研究文献接入 Agent 提供优先级建议。

### 一、两个项目的核心区别

`ReactionSeek` 的核心定位：

- 面向“反应/实验流程”抽取。
- 输入通常是 `Title + Procedure`，也就是合成步骤、实验段落、操作流程。
- 输出偏表格化条件信息：
  - `Reactants`
  - `Reactant amounts`
  - `Products`
  - `Product amounts`
  - `Solvents`
  - `Reaction temperature`
  - `Reaction time`
  - `Yield`
- 代表脚本：
  - `paperread/ReactionSeek/ReactionSeek/reaction_extract/extract_gpt.py`
  - `paperread/ReactionSeek/ReactionSeek/reaction_extract/structurelize.py`
  - `paperread/ReactionSeek/ReactionSeek/standardize/time_standardlize.py`
  - `paperread/ReactionSeek/ReactionSeek/standardize/name_to_smiles.py`

`NERRE` 的核心定位：

- 面向“材料实体和关系”抽取。
- 输入通常是标题、摘要，或按句切分后的科学文本。
- 输出偏结构化 JSON，不是实验表格，而是实体和关系图。
- 有两条主线：
  - `general_and_mofs`：抽一般材料信息与描述。
  - `doping`：抽掺杂相关关系。
- 代表 schema：
  - `general_and_mofs` 关注 `acronym`、`applications`、`name`、`formula`、`structure_or_phase`、`description`
  - `doping` 关注 `basemats`、`dopants`、`dopants2basemats`、`results`、`doping_modifiers`

简化理解：

- `ReactionSeek` 更像“实验条件抽取器”。
- `NERRE` 更像“材料知识图谱抽取器”。

### 二、从表面研究视角看，这两个项目各自能做什么

#### 1. ReactionSeek 能用于表面研究的部分

可直接利用的能力：

- 从实验段落抽取表面实验条件。
- 对表面反应、催化反应、吸附实验、表面处理流程进行表格化整理。
- 抽取温度、时间、溶剂、产物、产率等操作信息。

在表面研究中的典型适用文本：

- 催化反应实验部分
- 吸附/脱附实验步骤
- 表面修饰、浸渍、退火、还原、氧化、刻蚀流程
- ALD/CVD/溶胶凝胶/水热后处理段落
- 电催化测试前电极制备流程

可复用模块：

- `extract_gpt.py`
  - 适合抽表面实验过程中的“反应物/处理条件/产物”。
  - 如果把 prompt 从有机反应改成表面科学语境，可以抽：
    - 基底/载体
    - 吸附物或前驱体
    - 气氛
    - 处理温度
    - 保温时间
    - 洗涤/干燥/焙烧条件
    - 负载量
    - 转化率/选择性/收率
- `structurelize.py`
  - 可继续用于把 LLM 的 markdown 表格转成 CSV。
  - 这一层与领域关系不大，通用性强。
- `time_standardlize.py`
  - 可直接用于标准化表面实验中的保温时间、反应时间、吸附时间。
- `name_to_smiles.py`
  - 仅对分子型吸附物、反应物、探针分子、溶剂有帮助。
  - 对纯无机表面、晶面、缺陷位点、金属位点帮助有限。

对表面研究的局限：

- 现有 prompt 明显偏有机合成，不包含表面科学关键字段。
- 默认字段里没有：
  - `surface/substrate`
  - `facet`
  - `adsorbate`
  - `active_site`
  - `loading`
  - `calcination atmosphere`
  - `support`
  - `conversion/selectivity/activity/stability`
- 结果是它更适合“实验流程整理”，不适合“机理关系抽取”。

结论：

- `ReactionSeek` 最适合承担表面研究中的“实验条件结构化”工作。

#### 2. NERRE 能用于表面研究的部分

可直接利用的能力：

- 从标题、摘要、句子中抽材料实体、相、描述和应用。
- 抽“主体材料 - 掺杂元素”关系。
- 输出天然适合后续构图、索引和检索。

在表面研究中的典型适用文本：

- 表面催化材料摘要
- 吸附/催化/光催化/电催化综述摘要
- 描述表面掺杂、缺陷工程、异质结构筑、载体效应的句子
- 材料性能摘要，而不是详细实验步骤

可复用模块：

- `general_and_mofs`
  - 可直接迁移的字段：
    - `formula`
    - `name`
    - `structure_or_phase`
    - `description`
    - `applications`
  - 对表面研究的价值：
    - 提取催化剂材料名称
    - 提取相结构、形貌描述
    - 提取用途，如 photocatalyst、electrocatalyst、anode、cathode 等
  - 适合做“材料卡片”级别的信息抽取。
- `doping`
  - 对表面研究尤其有价值。
  - 可迁移的关系：
    - 基体材料 `basemats`
    - 掺杂元素/组分 `dopants`
    - 掺杂结果或固溶体 `results`
    - 掺杂修饰词 `doping_modifiers`
    - 掺杂链接 `dopants2basemats`
  - 对表面研究的实际对应：
    - `TiO2` 掺 `N`
    - `CeO2` 掺 `Cu`
    - `Pt/oxide` 中氧化物的异质原子掺杂
    - `surface sulfurization`
    - `vacancy-rich`、`single-doped`、`x wt%` 这类修饰信息

对表面研究的局限：

- `general_and_mofs` 当前 schema 不显式表示“表面”关系。
- `doping` 当前只强于掺杂，不直接覆盖：
  - 吸附物-表面关系
  - 晶面-性能关系
  - 缺陷位点-活性关系
  - 金属-载体相互作用
  - 反应物-中间体-产物路径
- 现有数据集主要是通用材料、MOF 和掺杂，并非表面催化专门语料。

结论：

- `NERRE` 最适合承担表面研究中的“材料实体与关系抽取”工作。
- 其中最值得迁移的是 `doping` 的句级关系抽取框架，而不是直接照搬它的原始任务定义。

### 三、如果目标是“聚焦表面研究”，优先保留哪些能力

优先级最高：

- `ReactionSeek` 的实验条件抽取链路
  - 用于抽表面实验流程和条件表。
- `NERRE/doping` 的关系抽取框架
  - 用于改造成表面关系抽取器。
- `NERRE/general_and_mofs` 的材料实体 schema
  - 用于抽材料名称、结构、相、形貌、应用。

优先级中等：

- `ReactionSeek/time_standardlize.py`
  - 统一时间单位，便于后续统计。
- `ReactionSeek/structurelize.py`
  - 保留为通用表格解析器。
- `ReactionSeek/name_to_smiles.py`
  - 仅在研究分子吸附、反应网络、有机探针时有价值。

优先级较低：

- `NERRE` 原始 MOF 专项内容
  - 与一般表面研究相关性有限，除非你要做多孔表面或 MOF 衍生催化材料。
- `NERRE` 原始掺杂 benchmark 结果文件
  - 可参考格式，但不应作为表面任务的核心资产。

### 四、真正适合表面研究的抽取目标建议

如果后续要把这两个项目改造成表面研究工具，更推荐形成两条线：

第一条线：表面实验条件抽取

- 来源基础：`ReactionSeek`
- 建议输出字段：
  - `material`
  - `surface_or_support`
  - `facet`
  - `dopant_or_modifier`
  - `adsorbate_or_reactant`
  - `atmosphere`
  - `solvent`
  - `temperature`
  - `time`
  - `loading`
  - `product`
  - `conversion`
  - `selectivity`
  - `yield`
  - `stability_or_cycles`

第二条线：表面知识关系抽取

- 来源基础：`NERRE`
- 建议输出 schema：
  - `surface_materials`
  - `facets`
  - `dopants`
  - `defects`
  - `active_sites`
  - `adsorbates`
  - `intermediates`
  - `products`
  - `properties`
  - `applications`
  - `links`

可重点覆盖的关系：

- 材料 `->` 晶面
- 材料 `->` 掺杂元素
- 材料 `->` 缺陷类型
- 材料 `->` 活性位点
- 表面 `->` 吸附物
- 活性位点 `->` 中间体
- 材料/表面 `->` 催化性能
- 处理条件 `->` 表面结构变化

### 五、面向当前目标的结论

如果你的研究重点是表面研究，而不是一般论文信息抽取，那么两个项目的定位应当这样分工：

- `ReactionSeek`：
  - 负责“实验段落 -> 条件表”的结构化。
  - 更适合处理 methods / experimental section。
- `NERRE`：
  - 负责“摘要/句子 -> 材料关系图”的结构化。
  - 更适合处理 abstract / results discussion。

从表面研究价值排序看：

- 第一优先：`NERRE/doping` 的句级关系框架
- 第二优先：`ReactionSeek/extract_gpt.py` 的流程条件抽取
- 第三优先：`NERRE/general_and_mofs` 的材料实体 schema
- 第四优先：`ReactionSeek` 的时间标准化与表格化后处理
- 第五优先：`name_to_smiles.py`，只在分子吸附/有机表面反应时保留

当前判断：

- 要做“表面催化/吸附/界面处理”知识整理，不能只留一个项目。
- 最合理的做法是：
  - 用 `ReactionSeek` 抽实验条件
  - 用 `NERRE` 抽材料与表面关系
  - 最后在 Agent 侧把两者并入统一 schema

## 已落地实现：paperread/surface

更新时间：2026-06-29

根据上面的筛选结果，已在 `paperread/` 下新建：

```text
paperread/surface/
```

当前已加入的脚本：

- `paperread/surface/extract_surface_conditions.py`
  - 来源思路：`ReactionSeek`
  - 功能：从表面研究相关文本中抽取条件表
  - 输出：
    - `*_raw.csv`
    - `*_table.csv`
- `paperread/surface/standardize_surface_time.py`
  - 来源思路：`ReactionSeek/time_standardlize.py`
  - 功能：把时间列标准化为分钟
- `paperread/surface/extract_surface_relations.py`
  - 来源思路：`NERRE/general_and_mofs` + `NERRE/doping`
  - 功能：抽取表面材料、晶面、掺杂、缺陷、活性位点、吸附物、产物、性质及其关系
- `paperread/surface/common.py`
  - 功能：统一输入加载、OpenAI 兼容调用、markdown 表格解析、JSON 提取
- `paperread/surface/README.md`
  - 功能：说明输入格式和三类脚本的用途

设计说明：

- 没有直接复制上游脚本，而是抽出可复用能力后重写成表面研究版本。
- 现在的 `surface/` 工具分成两条主线：
  - 条件抽取
  - 关系抽取
- 这与前面对 `ReactionSeek` 和 `NERRE` 的分工判断一致。

当前可运行性验证：

- 已验证模块方式可调用：
  - `python -m paperread.surface.extract_surface_conditions --help`
  - `python -m paperread.surface.extract_surface_relations --help`
- 已验证直接脚本方式可调用：
  - `python paperread/surface/extract_surface_conditions.py --help`
  - `python paperread/surface/extract_surface_relations.py --help`
- 已新增测试：
  - `tests/test_paperread_surface.py`
- 已使用内置 `unittest` 验证通过：

```bash
python -m unittest tests.test_paperread_surface -v
```

补充说明：

- 当前环境中未安装 `pytest`，因此本轮验证使用 `unittest`。
- 这些脚本已经具备逻辑上的独立入口，但是否“抽得准”仍取决于后续是否继续针对表面研究语料优化 prompt 和 schema。

后续补充：

- 已根据“需要反应参数和材料参数”这一要求，扩展 `paperread/surface/` 的输出字段。
- `extract_surface_conditions.py` 现在显式覆盖两类参数：
  - 反应参数：`Reaction Type`、`Feed/Concentration`、`Atmosphere`、`Pressure`、`Gas Flow`、`Solvent`、`pH`、`Temperature`、`Time`、`Potential/Bias`、`Current Density`、`Conversion`、`Selectivity`、`Yield`、`Rate/Activity`、`Stability/Cycles`
  - 材料参数：`Material`、`Composition`、`Phase`、`Morphology/Size`、`Surface Area`、`Surface/Support`、`Facet`、`Active Site`、`Defect`、`Dopant/Modifier`、`Loading`
- `extract_surface_relations.py` 现在新增：
  - `material_parameters`
  - `reaction_parameters`
- 这样后续既能做条件表统计，也能做参数级关系图谱整理。

## surface 子项目统一整理

更新时间：2026-06-29

当前 `paperread/surface/` 已不再只是几个分散脚本，而是一个面向“表面材料上的各种化学反应”的统一子项目。

统一思路：

- 将 `ReactionSeek` 的“实验条件抽取能力”和 `NERRE` 的“材料/关系抽取能力”合并。
- 目标不再是分别处理“反应”或“材料”，而是统一处理：
  - 表面材料
  - 表面位点
  - 反应物/吸附物
  - 反应条件
  - 产物与性能
  - 它们之间的关系

当前目录：

```text
paperread/surface/
  __init__.py
  common.py
  extract_surface_conditions.py
  standardize_surface_time.py
  extract_surface_relations.py
  run_surface_pipeline.py
  README.md
  examples/
    sample_surface_input.json
```

### surface 文件夹中的使用情况

推荐默认入口：

- `paperread/surface/run_surface_pipeline.py`

用途：

- 对一篇或一组表面材料反应文献，一次性产出：
  - 条件抽取结果
  - 时间标准化结果
  - 材料/反应关系抽取结果

标准用法：

```bash
python -m paperread.surface.run_surface_pipeline \
  paperread/surface/examples/sample_surface_input.json \
  --output-dir paperread/surface/output
```

输出内容：

- `*_raw.csv`
  - 条件抽取的原始模型输出
- `*_table.csv`
  - 结构化条件表
- `*_time.csv`
  - 标准化后的时间表
- `*_surface_relations.jsonl`
  - 结构化关系抽取结果

三个核心脚本分工：

- `extract_surface_conditions.py`
  - 适合 methods / procedure / experimental section
  - 重点输出反应参数和材料参数表
- `standardize_surface_time.py`
  - 适合对已有表中的 `Time` 列做统一标准化
- `extract_surface_relations.py`
  - 适合 abstract / results / discussion
  - 重点输出材料、表面、位点、吸附物、反应参数、材料参数及 links

### 已完成验证

本轮对 `surface` 子项目做了两层验证：

1. CLI 入口验证

- 已验证以下模块入口可用：
  - `python -m paperread.surface.extract_surface_conditions --help`
  - `python -m paperread.surface.standardize_surface_time --help`
  - `python -m paperread.surface.extract_surface_relations --help`
  - `python -m paperread.surface.run_surface_pipeline --help`

2. 离线功能验证

- 已新增离线测试：
  - `tests/test_paperread_surface.py`
- 通过 mock LLM 返回值，验证了：
  - 条件抽取流程可写出 CSV
  - 时间标准化流程可写出结果表
  - 关系抽取流程可写出 JSONL
  - 统一 pipeline 可串联运行

验证命令：

```bash
python -m unittest tests.test_paperread_surface -v
```

验证结果：

- 4 个测试全部通过
- 当前验证的是“子项目逻辑和接口可用”
- 尚未验证真实 API 条件下的抽取质量

当前判断：

- `paperread/surface/` 已经可以作为独立的表面材料化学反应处理子项目使用。
- 下一阶段重点不应再是目录整理，而应转向：
  - 用真实表面文献样本调 prompt
  - 固化更稳定的 surface schema
  - 再补少量真实 case 的回归测试

## 新增 PDF 入口逻辑

更新时间：2026-06-29

针对“从论文 PDF 开始读取，然后提取反应与材料要素”的需求，`paperread/surface/` 现已新增 PDF ingestion 层。

新增文件：

- `paperread/surface/ingest_pdf.py`

当前逻辑链：

```text
PDF
-> pdftotext 提取全文文本
-> pdfinfo 读取元数据标题
-> 章节切分
-> 生成两类 JSON 输入
   -> 条件抽取输入
   -> 关系抽取输入
-> run_surface_pipeline.py
-> 反应参数 + 材料参数 + 表面关系输出
```

章节切分后的分流策略：

- 条件抽取输入：
  - 优先使用 `Experimental / Methods / Materials and Methods`
  - 必要时补入 `Results`
- 关系抽取输入：
  - 优先使用 `Abstract / Results and Discussion / Results / Discussion / Conclusion`
  - 缺失时退回全文

这意味着当前 `surface` 已经不是单纯接收手工整理 JSON 的工具，而是支持：

- `JSON -> 抽取`
- `PDF -> 文本分流 -> 抽取`

### 使用方式

直接处理 PDF：

```bash
python -m paperread.surface.run_surface_pipeline your_paper.pdf --output-dir paperread/surface/output
```

也可以只做 PDF 分段与中间输入生成：

```bash
python -m paperread.surface.ingest_pdf your_paper.pdf --output-dir paperread/surface/output
```

PDF 输入时会额外生成：

- `*_text.txt`
  - 从 PDF 抽出的原始文本
- `*_sections.json`
  - 章节切分结果
- `*_conditions_input.json`
  - 用于条件抽取的中间 JSON
- `*_relations_input.json`
  - 用于关系抽取的中间 JSON

### 当前验证状态

已新增并通过的验证包括：

- `ingest_pdf.py` CLI 帮助页可用
- `run_surface_pipeline.py` 已支持 `--input-format {auto,json,pdf}`
- 新增离线测试覆盖：
  - PDF 章节切分辅助函数
  - PDF ingestion 后接统一 pipeline 的流程

验证命令：

```bash
python -m unittest tests.test_paperread_surface -v
```

当前结果：

- 6 个测试全部通过

当前边界：

- 现在已经具备“从 PDF 入口开始”的逻辑能力。
- 但 PDF 质量仍依赖 `pdftotext` 对版面的解析效果。
- 双栏排版、复杂表格、图注、参考文献噪声、扫描版 PDF 仍可能影响抽取质量。

## 本轮补充：`tests/test2.pdf` 实测与摘要格式调整

更新时间：2026-06-29

本轮处理内容：

- 对 `tests/test2.pdf` 进行了新一轮抽取实验。
- 由于整篇 PDF 直接送入模型时触发上下文限制，因此先对论文关键内容做压缩整理，再送入 `surface` 抽取链路。
- 输出文件继续统一放在 `tests/` 下。

本轮产出文件：

- `tests/test2_api_table.csv`
- `tests/test2_api_time.csv`
- `tests/test2_api_surface_relations.jsonl`
- `tests/test2_api_summary.txt`

本轮关键调整：

- 修改 `paperread/surface/summarize_surface_outputs.py`
- 将关系抽取结果中的以下部分改为竖排输出：
  - `材料`
  - `材料参数`
  - `反应参数`
  - `性能`

当前摘要文件格式已确认：

```text
- 材料：
  - item1
  - item2
- 材料参数：
  - item1
  - item2
- 反应参数：
  - item1
  - item2
- 性能：
  - item1
  - item2
```

当前结论：

- `surface` 子项目已经支持：
  - 从 PDF 提取文本
  - 分流条件抽取与关系抽取输入
  - 输出条件表、时间标准化结果、表面关系结果、人工可读摘要
- 最新摘要输出格式已经更适合后续人工浏览和整理化学反应相关信息。

## 本轮补充：关系文件改为竖排输出

更新时间：2026-06-29

本轮主要工作：

- 继续完善 `paperread/surface/` 子项目，用于表面材料与化学反应信息抽取。
- 以 `tests/test2.pdf` 为测试论文，重新执行表面关系抽取与摘要生成。
- 将 `test2_api_surface_relations.jsonl` 的输出格式调整为竖排、多行、可直接阅读的 JSON。
- 保持摘要文件 `test2_api_summary.txt` 中的材料、材料参数、反应参数、性能部分为竖排列表。

本轮关键修改：

- 修改 `paperread/surface/extract_surface_relations.py`
  - 原先输出为单行 JSONL。
  - 现在改为带缩进的多行 JSON，便于直接查看关系抽取结果。
- 修改 `paperread/surface/summarize_surface_outputs.py`
  - 兼容读取旧的一行 JSONL。
  - 兼容读取新的多行竖排 JSON。
- 修改 `tests/test_paperread_surface.py`
  - 调整断言，适配新的关系文件格式。

本轮生成与确认的输出：

- `tests/test2_api_surface_relations.jsonl`
  - 现在为竖排 JSON 输出。
- `tests/test2_api_summary.txt`
  - 摘要中的反应相关部分已按竖排输出。

验证结果：

```bash
python -m unittest tests.test_paperread_surface -v
```

- 7 个测试全部通过。

当前状态：

- `surface` 子项目已经支持从 PDF 相关内容中抽取：
  - 材料
  - 材料参数
  - 反应参数
  - 性能
  - 关系链接
- 输出格式已经更适合人工审阅和后续整理。

## 日志约定

- 从现在开始，这个项目的工作日志默认统一写入 `work_log.md`。

## 本轮补充：版本升级到 2.0.0

更新时间：2026-06-29

本轮处理内容：

- 将项目版本号从 `1.0.0` 升级到 `2.0.0`。
- 原因是当前项目已经新增论文读取与信息提取能力，功能范围明显扩展，不再只是初始版本能力。

本轮修改文件：

- `pyproject.toml`
  - `project.version = "2.0.0"`
- `CHANGELOG.md`
  - 新增 `v2.0.0 (2026-06-29)` 条目
  - 记录以下新增能力：
    - `paperread/` 论文读取与信息提取工作流
    - `ReactionSeek` 与 `NERRE` 接入
    - `paperread/surface/` 的 PDF 读取、表面材料抽取、反应参数抽取与摘要输出

## 本轮补充：同步 API 元数据版本

更新时间：2026-06-29

本轮处理内容：

- 检查了前端、文档和服务端代码中的硬编码版本号。
- 确认真正需要同步的是后端 API 元数据中的版本号，而不是前端依赖或模型文件名。

本轮修改文件：

- `web/main.py`
  - 将 `FastAPI(title="Agent Graph API", version="1.0.0")`
  - 更新为 `FastAPI(title="Agent Graph API", version="2.0.0")`

检查结论：

- `pyproject.toml` 已是 `2.0.0`
- `CHANGELOG.md` 已新增 `v2.0.0`
- `web/main.py` 现已同步到 `2.0.0`
- `web/vite-frontend/package.json` 中的 `0.1.0` 是前端包自身版本，当前不作为主项目版本处理
