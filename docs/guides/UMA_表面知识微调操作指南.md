# UMA 表面相关知识微调操作指南

## 1. 目标和总体建议

本文首先解读
[`qiqb-osaka/mace-osaka26`](https://github.com/qiqb-osaka/mace-osaka26)
仓库中的机器学习原子间势（MLIP）训练方式，然后给出使用个人表面数据对
Meta FAIR 的 UMA（Universal Models for Atoms）模型进行微调的完整方案。

本文面向以下类型的研究：

- ZnO 等无机或氧化物表面；
- H₂O 在表面的吸附；
- 有机分子在无机表面的吸附；
- 表面缺陷、重构和化学反应；
- 基于机器学习势的结构优化与分子动力学；
- 希望给通用 UMA 模型补充特定表面领域知识。

核心建议是：

> 不要尝试用个人计算资源从零训练一个新的通用 UMA。更现实的路线是选择
> 与目标 DFT 计算水平一致的 UMA task，以 `uma-s-1p2` 预训练模型为起点，
> 使用自己计算的表面、吸附和反应构型做单任务微调，再通过主动学习不断
> 补充模型不可靠的表面构型。

推荐的总体流程为：

```text
确定目标表面和物理问题
        ↓
确定统一的 DFT 理论水平
        ↓
选择对应 UMA task
        ↓
生成 clean slab、吸附、缺陷、扰动、AIMD 和反应构型
        ↓
统一进行 DFT 能量、力和应力标注
        ↓
按物理体系/轨迹划分 train、validation、test
        ↓
转换为 ASE-LMDB
        ↓
从 uma-s-1p2 进行单任务微调
        ↓
测试能量、力、吸附能、结构和 MD 稳定性
        ↓
主动学习补充失败构型
```

## 2. MACE-Osaka26 的训练方式

### 2.1 仓库包含什么

MACE-Osaka26 仓库非常精简，主要提供：

- 模型说明；
- MACE-Osaka24 训练脚本；
- MACE-Osaka26 训练脚本；
- 训练数据来源说明；
- 模型发布文件。

仓库并没有包含完整的数据生成、DFT 计算和数据清洗流水线。因此，从仓库
可以准确看到模型结构和主要训练参数，但无法仅靠仓库完全复现所有数据处理
细节。

官方仓库：

<https://github.com/qiqb-osaka/mace-osaka26>

训练脚本：

<https://github.com/qiqb-osaka/mace-osaka26/blob/main/mace_osaka26/mace-osaka26-small.sh>

### 2.2 训练数据构成

MACE-Osaka26 的训练集由两大部分组成。

#### MACE-Osaka24 数据

包含：

- 无机晶体 MPtrj；
- SPICE；
- QMug；
- 水团簇；
- 三肽；
- MACE-OFF23 相关有机分子数据。

这些数据跨越无机晶体和有机分子，并且来自不同第一性原理计算条件。
MACE-Osaka24 使用 Total Energy Alignment（TEA，总能量对齐）方法整合不同
来源的数据。

#### HE26 数据

HE26 是面向重元素的新数据集，包括：

- 多种重元素；
- 次锕系元素；
- 来源于实验文献和理论计算的数据；
- 用于扩展模型元素覆盖范围的数据。

通过 MACE-Osaka24 数据与 HE26 数据的组合，MACE-Osaka26 最终覆盖 97 个
元素，并尝试在同一个模型中表示分子、晶体和重元素体系。

这体现了一个重要思想：

> 给模型增加某一领域的知识，本质上是增加该领域中有代表性、物理一致且
> 标签可靠的数据，而不是简单修改模型名称或增加几个稳定结构。

### 2.3 模型结构

MACE-Osaka26 的训练脚本包含：

```bash
--model="ScaleShiftMACE"
--interaction_first="RealAgnosticResidualInteractionBlock"
--interaction="RealAgnosticResidualInteractionBlock"
--num_interactions=2
--correlation=3
--max_ell=3
--r_max=6.0
--max_L=0
--num_channels=128
--num_radial_basis=10
--MLP_irreps="16x0e"
```

主要含义如下。

#### `ScaleShiftMACE`

使用带能量尺度和平移处理的 MACE 模型。它有助于把模型内部输出映射到训练
数据的能量尺度。

#### `num_interactions=2`

模型执行两层原子消息传递。每一层都聚合截断半径内相邻原子的信息。

#### `correlation=3`

使用较高阶多体相关特征，使模型不仅表示简单二体距离，还能表示复杂局域
化学环境。

#### `max_ell=3`

等变特征保留到 \(l=3\) 的角动量表示，从而编码较丰富的方向和角度信息。

#### `r_max=6.0`

局域环境截断半径为 6 Å。距离超过截断半径的直接原子相互作用不会在同一层
消息传递中直接出现。

#### `num_channels=128`

隐藏特征通道数为 128，决定模型表示能力和计算量。

#### `pair_repulsion`

训练脚本启用了：

```bash
--pair_repulsion
```

短程原子排斥有助于降低原子距离极小时模型产生严重非物理吸引的风险。这对于
高温 MD、碰撞、表面反应或初始结构存在短接触时尤其重要。

#### `distance_transform=Agnesi`

训练脚本使用：

```bash
--distance_transform="Agnesi"
```

对径向距离进行平滑变换，以帮助模型描述近程和较远局域环境。

### 2.4 能量、力和应力联合训练

训练脚本使用：

```bash
--loss='universal'
--energy_weight=1
--forces_weight=10
--compute_stress=True
--stress_weight=100
--stress_key='stress'
```

模型同时拟合：

- 总能量；
- 原子力；
- 应力张量。

其中：

```text
energy_weight = 1
forces_weight = 10
stress_weight = 100
```

这些数字是 MACE 当前损失定义和归一化体系下的权重，不能直接复制到 UMA
配置中。

对于表面模型，力标签特别重要，原因包括：

- 一个含 \(N\) 个原子的构型提供一个总能量，但可提供 \(3N\) 个力分量；
- 结构优化由力驱动；
- 分子动力学轨迹由力决定；
- 表面重构和吸附路径对局域力非常敏感；
- 只拟合最低能量点无法保证离开极小点后仍有合理势能面。

应力标签则对以下任务更重要：

- 晶胞弛豫；
- 体相材料；
- 弹性性质；
- 应变表面；
- 表面应力；
- NPT 或可变晶胞模拟。

如果只研究固定晶胞 slab 的吸附和 NVT MD，能量和力通常是最核心的标签。

### 2.5 优化器和训练参数

训练脚本使用：

```bash
--lr=0.005
--weight_decay=1e-8
--ema
--ema_decay=0.995
--scheduler_patience=5
--batch_size=16
--valid_batch_size=32
--max_num_epochs=200
--patience=50
--amsgrad
--clip_grad=100
--keep_checkpoints
--distributed
```

主要含义：

- 初始学习率为 `0.005`；
- 很小的权重衰减；
- 使用指数移动平均 EMA；
- 最多训练 200 个 epoch；
- 验证指标长期不改善时提前停止；
- 使用 AMSGrad；
- 梯度裁剪上限为 100；
- 保留 checkpoint；
- 支持分布式训练。

需要注意：

> 这是从头训练通用 MACE 的配置，不是使用小规模个人数据微调 UMA 的配置。

尤其 `lr=0.005` 对 UMA 微调通常明显过大，不能直接照搬。

## 3. MACE-Osaka26 与 UMA 的核心区别

虽然两者都是机器学习原子间势，但训练框架和多领域机制不同。

| 项目 | MACE-Osaka26 | UMA |
| --- | --- | --- |
| 软件框架 | `mace-torch` | `fairchem-core` |
| 主要结构 | ScaleShiftMACE | eSEN/UMA + MoLE |
| 训练入口 | MACE `run_train.py` | `fairchem` CLI |
| 配置形式 | 命令行参数 | Hydra YAML |
| 训练数据格式 | MACE 数据目录 | ASE-LMDB |
| 多领域方式 | TEA 等数据整合 | task embedding + MoLE 路由 |
| 个人定制推荐 | MACE checkpoint 微调 | UMA 单任务微调 |
| 推理任务标签 | 没有 UMA task | 必须指定 UMA task |

UMA 使用 Mixture of Linear Experts（MoLE）结构。模型路由依赖：

- task；
- 元素组成；
- 对 `omol` 分子任务，还使用电荷和自旋多重度。

UMA 模型官方说明：

<https://fair-chem.github.io/uma/>

因此，对 UMA 添加表面知识时不能只考虑元素和坐标，还必须明确：

1. 新数据属于哪个 UMA task；
2. 新数据采用什么 DFT 理论水平；
3. 微调后推理时使用哪个 task；
4. 新数据的能量零点是否与该 task 的已有知识一致。

## 4. UMA 模型和 task 的选择

当前优先推荐从：

```text
uma-s-1p2
```

开始，而不是从零训练 UMA。

`uma-s-1p2` 相对中型 UMA 更适合个人微调：

- 显存需求较低；
- 训练速度更快；
- 仍然具有很强的预训练知识；
- 更适合先验证整个数据和训练流程。

### 4.1 UMA task 对比

| UMA task | 主要数据/理论水平 | 主要适用方向 |
| --- | --- | --- |
| `omol` | OMol25；ORCA；wB97M-V/def2-TZVPD | 非周期分子、有机化学、聚合物 |
| `omc` | OMC25；VASP PBE+D3 | 分子晶体 |
| `omat` | OMat24；VASP PBE/PBE+U | 无机体相材料 |
| `oc20` | VASP RPBE；无色散 | 催化表面，但不含氧化物和显式溶剂 |
| `odac` | VASP PBE+D3 | MOF、CO₂/H₂O 吸附 |
| `oc22` | VASP PBE+U、自旋极化 | 氧化物催化剂和氧化物载体 |
| `oc25` | VASP RPBE+D3、偶极修正 | 表面、吸附、电催化和界面 |

### 4.2 对 ZnO 表面的选择

如果目标是：

- ZnO 表面；
- 氧化物缺陷；
- 氧空位；
- ZnO 表面重构；
- PBE+U 数据；

优先考虑：

```text
uma-s-1p2 + oc22
```

如果目标是：

- H₂O/ZnO 吸附；
- 有机分子/ZnO 吸附；
- 含色散作用的表面；
- 表面界面；
- 使用 RPBE+D3 和偶极修正；

优先考虑：

```text
uma-s-1p2 + oc25
```

如果采用 `PBE-D3(BJ)`，它与 `oc22` 和 `oc25` 的基础理论水平都不完全相同。
仍可选择最接近的 task 作为预训练起点，但必须认识到：

- 这是跨理论水平的微调；
- 微调数据必须在内部保持统一；
- 需要更多数据纠正预训练模型的能量定义；
- 必须在独立 DFT 测试集上验证；
- 不能把不同泛函的绝对总能量直接混在一起。

对于当前的 ZnO + 水/有机吸附方向，如果可以重新统一 DFT 设置，推荐：

```text
base model: uma-s-1p2
task: oc25
DFT: RPBE+D3
periodic code: VASP
surface correction: dipole correction
```

如果必须沿用 PBE+U 氧化物数据库，则更适合从 `oc22` 开始。

## 5. 在训练前固定 DFT 标签标准

这是整个项目最重要的步骤。

所有训练、验证和测试数据应尽量统一：

- 交换相关泛函；
- 色散修正；
- 赝势版本；
- Hubbard \(U\)；
- 自旋设置；
- 平面波截断能；
- k 点密度；
- smearing 方法；
- SCF 收敛阈值；
- 离子步收敛阈值；
- 偶极修正；
- 周期边界；
- 真空层定义；
- 能量零点；
- stress 单位和符号。

不要无处理地把以下数据混入同一 task：

```text
PBE
PBE+U
PBE-D3
PBE-D3(BJ)
RPBE
RPBE-D3
不同 U 值
不同 PAW/赝势版本
不同磁性设置
不同能量参考
```

### 5.1 为什么绝对能量一致性重要

模型拟合的是总能量函数：

\[
E = E(\mathbf{R}, \mathbf{Z}, \mathbf{h})
\]

其中：

- \(\mathbf{R}\) 是原子坐标；
- \(\mathbf{Z}\) 是元素；
- \(\mathbf{h}\) 是晶胞。

如果相同结构在不同 DFT 设置下具有不同能量零点或不同化学趋势，模型会收到
互相矛盾的监督信号。

MACE-Osaka24 使用 TEA 处理多源数据能量对齐，但 UMA 的个人单任务微调脚本
不会自动为任意混合 DFT 数据完成等价对齐。

### 5.2 建议保存计算元数据

每个 DFT 构型建议记录：

```text
functional
dispersion
pseudopotential
U value
spin setting
cutoff
k-point mesh
smearing
dipole correction
SCF threshold
calculation code/version
source trajectory
surface Miller index
adsorbate
coverage
charge
```

即使这些字段不全部作为模型输入，也应保存在数据审计记录中。

## 6. 表面训练集应该包含什么

### 6.1 清洁表面

应覆盖：

- 不同晶面；
- 不同表面终止；
- 不同 slab 厚度；
- 不同真空层；
- 不同面内超胞；
- 对称和非对称 slab；
- 固定底层和完全放松结构；
- 表面原子随机扰动；
- 压缩和拉伸；
- 表面重构；
- 高温表面快照。

对于 ZnO，至少可逐步考虑：

```text
(10-10)
(11-20)
(0001)
(000-1)
```

其中极性表面需要明确：

- 电荷补偿方式；
- 化学计量；
- slab 对称性；
- 偶极修正；
- 表面终止。

不能把物理意义不同的补偿策略混为一种表面。

### 6.2 表面缺陷

应考虑：

- 氧空位；
- Zn 空位；
- 表面替位；
- 间隙原子；
- 吸附原子；
- 台阶；
- 棱边；
- 缺陷浓度；
- 缺陷间距；
- 不同电荷或磁性状态（如果 DFT 体系允许）。

缺陷附近的局部环境通常与理想晶面差异很大，是通用模型容易外推失败的区域。

### 6.3 吸附体系

每种吸附物建议覆盖：

- 多个吸附位点；
- 多种初始方向；
- 多个吸附高度；
- 分子绕不同轴旋转；
- 分子内键扰动；
- 不同覆盖度；
- 单分子和多分子；
- 共吸附；
- 吸附前、吸附中和吸附后构型；
- 脱附构型；
- 解离构型；
- 表面反应构型。

对于 H₂O/ZnO，不应只包含最低能分子吸附结构。建议包括：

```text
clean ZnO slab
isolated H2O
H2O approaching Zn site
H2O approaching O site
molecular adsorption
OH + H dissociative adsorption
proton-transfer structures
desorption structures
multiple-water structures
surface hydroxylation
```

对于 2-壬酮或其他有机分子，建议包括：

- 羰基朝向表面；
- 烃链平行或垂直表面；
- 多个表面 Zn/O 位点；
- 多种链构象；
- 不同周期覆盖度；
- 分子与周期镜像距离变化；
- 弱吸附和脱附区域；
- 高温 MD 中的构象变化。

### 6.4 非平衡构型

训练稳定 MLIP 的关键不只是能量极小结构，还包括离开极小点后的势能面。

应添加：

- DFT 几何优化轨迹中间帧；
- AIMD 轨迹帧；
- 正常模扰动；
- 随机原子位移；
- 晶胞微小应变；
- 吸附高度扫描；
- 键长扫描；
- 极短接触和排斥区；
- NEB 中间图像；
- 过渡态附近结构；
- 模型预测失败的构型。

建议包含多个温度，例如：

```text
300 K
600 K
900 K
```

温度范围应与未来实际模拟范围匹配。若最终只研究 300 K，也可以包含一定量
更高温构型以扩大稳健区域，但不能让大量高温解离结构改变目标化学空间。

### 6.5 参考体系

如果研究吸附能：

\[
E_\mathrm{ads}
=E_{\mathrm{slab+ads}}
-E_{\mathrm{slab}}
-E_{\mathrm{adsorbate}}
\]

训练集和测试集应同时包含：

- 吸附体系；
- 相同 slab 设置下的清洁表面；
- 相同 DFT 设置下的气相吸附物；
- 必要时不同吸附物构象；
- 相同超胞和修正策略。

否则可能出现：

- 总能量 MAE 很小；
- 原子力也不错；
- 但吸附能仍存在系统偏差。

### 6.6 排斥区数据

MD 中模型可能访问训练集以外的短原子间距。建议加入少量受控排斥区构型：

- 压缩吸附高度；
- 拉近两个非键原子；
- 小幅压缩晶胞；
- 对反应物施加受控键长扫描。

排斥区数据需要物理和数值检查，不能生成大量严重重叠、DFT 本身无法收敛的
结构。

## 7. 初始数据规模建议

对于第一版 ZnO 表面模型，可以从约 1000–2000 个高质量构型开始。

一个示例分配为：

| 数据类型 | 建议初始数量 |
| --- | ---: |
| 体相和应变结构 | 50–150 |
| 清洁表面 | 100–300 |
| 表面缺陷 | 100–300 |
| 吸附位点和取向 | 300–800 |
| 优化轨迹中间帧 | 200–500 |
| AIMD 帧 | 300–1000 |
| 排斥区/反应路径 | 50–200 |

这些范围不是硬性要求。比数量更重要的是：

- 数据多样性；
- 标签一致性；
- 是否覆盖未来模拟会访问的构型；
- 是否避免大量重复帧；
- 是否包含模型当前最薄弱的区域。

不要把一条 AIMD 轨迹的每一步全部加入数据集。相邻帧高度相关，会浪费 DFT
和训练资源。

## 8. 数据去重和筛选

可以使用以下方法筛选多样构型：

- 能量分层采样；
- 最大力分层采样；
- 温度分层采样；
- 吸附高度分箱；
- SOAP 描述符；
- Farthest Point Sampling（FPS）；
- 聚类后选择中心构型；
- 多模型 ensemble 分歧；
- 当前 UMA 与 DFT 的误差；
- 当前模型预测不确定性。

一个实用流程是：

```text
生成大量候选结构
        ↓
删除明显重复结构
        ↓
按晶面、缺陷、吸附物分类
        ↓
计算结构描述符
        ↓
聚类或 FPS 选择代表结构
        ↓
进行 DFT 标注
```

比起先对所有相似结构做 DFT，再进行筛选，优先在 DFT 前筛选通常更节约计算
资源。

## 9. 正确划分训练、验证和测试集

### 9.1 不要随机拆分相邻轨迹帧

错误方式：

```text
同一条 AIMD 轨迹的 1、4、7 帧进入训练集
同一条轨迹的 2、5、8 帧进入验证集
同一条轨迹的 3、6、9 帧进入测试集
```

相邻帧非常相似，会造成严重的数据泄漏，得到过于乐观的验证误差。

### 9.2 按轨迹和物理体系分组

正确方式是按以下单位整体划分：

- 一条完整轨迹；
- 一个吸附位点；
- 一个晶面；
- 一个缺陷类型；
- 一个吸附物；
- 一个覆盖度；
- 一次独立结构搜索。

示例：

```text
训练集：
  晶面 A、B
  吸附位点 1、2、3
  温度轨迹 1、2

验证集：
  独立吸附位点 4
  独立轨迹 3
  不同覆盖度

测试集：
  未见过的晶面
  未见过的缺陷
  未见过的吸附方向
  独立 AIMD
  独立反应路径
```

### 9.3 两类测试集

建议同时建立：

#### In-domain 测试集

与训练分布接近，但不包含重复结构，用来衡量拟合能力。

#### Out-of-domain 测试集

包含：

- 新晶面；
- 新缺陷；
- 新覆盖度；
- 新吸附取向；
- 更高温构型；
- 反应路径。

用来衡量真正的泛化和实际模拟风险。

## 10. UMA 官方微调框架

FAIRChem 当前使用：

- `fairchem-core`；
- Hydra YAML 配置；
- ASE-LMDB 训练数据；
- `fairchem` CLI；
- UMA checkpoint。

官方微调文档：

<https://github.com/facebookresearch/fairchem/blob/main/docs/core/common_tasks/fine_tuning.md>

官方仓库：

<https://github.com/facebookresearch/fairchem>

官方文档明确说明：

- UMA 微调与标准训练使用同一套训练基础设施；
- 输入数据必须转换为 ASE-LMDB；
- 官方脚本可以从 ASE 能读取的格式建立 LMDB；
- 可处理 CIF、traj、extxyz 等；
- 一次只正式支持微调一个 UMA task；
- 可以训练能量、能量+力或能量+力+应力。

## 11. 安装环境

### 11.1 获取 UMA 权限

首先需要：

1. Hugging Face 账号；
2. 申请访问 UMA 模型；
3. 创建 Hugging Face token；
4. 在训练环境中登录。

一般使用：

```bash
huggingface-cli login
```

UMA 模型页面：

<https://huggingface.co/facebook/UMA>

### 11.2 克隆 FAIRChem

```bash
git clone https://github.com/facebookresearch/fairchem.git
cd fairchem
```

### 11.3 安装开发版本

仓库目录结构可能随版本变化。当前通常使用：

```bash
pip install -e packages/fairchem-core[dev]
```

部分官方文档或旧版本可能显示：

```bash
pip install -e src/packages/fairchem-core[dev]
```

应先检查实际目录：

```bash
find . -maxdepth 4 -type d -name fairchem-core
```

然后使用当前仓库真实路径安装。

### 11.4 检查安装

```bash
python -c "import fairchem.core; print(fairchem.core.__version__)"
fairchem --help
```

检查 GPU：

```bash
nvidia-smi
python -c "import torch; print(torch.cuda.is_available()); print(torch.cuda.get_device_name(0))"
```

## 12. 准备 ASE 可读取的训练文件

建议目录：

```text
surface_finetune/
├── raw/
├── train/
│   ├── train_clean_surface.extxyz
│   ├── train_adsorption.extxyz
│   └── train_aimd.traj
├── val/
│   └── val.extxyz
├── test/
│   └── test.extxyz
├── lmdb/
├── runs/
└── metadata/
```

### 12.1 每个 ASE Atoms 对象应包含

至少：

- 元素；
- 坐标；
- 晶胞；
- 周期边界；
- 总能量；
- 原子力。

如果使用应力训练，还需包含：

- stress；
- 正确的单位；
- 正确的张量顺序；
- 正确的符号约定。

### 12.2 extxyz 示例字段

典型 extxyz 会在注释行中保存：

```text
Lattice="..."
Properties=species:S:1:pos:R:3:forces:R:3
energy=...
stress="..."
pbc="T T F"
```

具体字段是否被转换脚本正确识别，必须先用 ASE 检查：

```python
from ase.io import read

atoms_list = read("train.extxyz", index=":")
print("structures:", len(atoms_list))

atoms = atoms_list[0]
print("symbols:", atoms.get_chemical_symbols())
print("cell:", atoms.cell)
print("pbc:", atoms.pbc)
print("energy:", atoms.get_potential_energy())
print("forces shape:", atoms.get_forces().shape)
print("stress:", atoms.get_stress())
```

如果 `get_potential_energy()` 或 `get_forces()` 报错，说明标签没有按 ASE 能识别
的方式写入。

### 12.3 单位

通常应确保：

```text
energy: eV
forces: eV/Å
positions: Å
stress: ASE 期望的单位和符号
```

转换前应抽查若干构型，并与原始 DFT 输出逐项比较。

## 13. 转换为 UMA 微调数据集

先定位脚本：

```bash
find . -name create_uma_finetune_dataset.py
```

脚本一般位于类似：

```text
packages/fairchem-core/src/fairchem/core/scripts/create_uma_finetune_dataset.py
```

或某些版本中的：

```text
src/fairchem/core/scripts/create_uma_finetune_dataset.py
```

### 13.1 能量和力训练

以 `oc25` 为例：

```bash
python packages/fairchem-core/src/fairchem/core/scripts/create_uma_finetune_dataset.py \
  --train-dir /path/to/surface_finetune/train \
  --val-dir /path/to/surface_finetune/val \
  --test-dir /path/to/surface_finetune/test \
  --output-dir /path/to/surface_finetune/lmdb \
  --uma-task oc25 \
  --regression-task ef
```

### 13.2 能量、力和应力训练

```bash
python packages/fairchem-core/src/fairchem/core/scripts/create_uma_finetune_dataset.py \
  --train-dir /path/to/surface_finetune/train \
  --val-dir /path/to/surface_finetune/val \
  --test-dir /path/to/surface_finetune/test \
  --output-dir /path/to/surface_finetune/lmdb \
  --uma-task oc25 \
  --regression-task efs
```

### 13.3 Regression task

可选：

| 参数 | 标签 |
| --- | --- |
| `e` | 仅能量 |
| `ef` | 能量 + 力 |
| `efs` | 能量 + 力 + 应力 |

对于表面 MD，优先使用：

```text
ef
```

对于还要研究：

- 晶胞弛豫；
- 表面应力；
- 体相与表面联合模型；
- 应变；

可使用：

```text
efs
```

即使只训练 `e` 或 `ef`，模型仍可通过能量梯度给出力或应力，但没有相应标签
直接监督时，其准确性不能保证。

### 13.4 单 task 限制

官方流程一次只支持一个 UMA task：

```text
omol
odac
oc20
oc22
oc25
omat
omc
```

不要在第一版项目中尝试同时微调 `oc22 + oc25 + omat`。多任务微调涉及：

- task 映射；
- 多数据集采样比例；
- 不同 DFT 理论水平；
- 不同能量参考；
- 多任务 loss 平衡；
- MoLE 路由。

个人项目应先把一个 task 做可靠。

## 14. 生成和检查微调 YAML

数据转换脚本会生成类似：

```text
uma_sm_finetune_template.yaml
```

官方基础配置一般包含：

```yaml
job:
  device_type: CUDA
  scheduler:
    mode: LOCAL
    ranks_per_node: 1
    num_nodes: 1
  debug: true
  run_dir: /path/to/runs
  run_name: uma_surface_finetune

base_model_name: uma-s-1p2
max_neighbors: 300
epochs: 1
steps: null
batch_size: 2
lr: 4e-4
```

注意：

- Hydra YAML 中 `_target_` 可实例化 Python 对象；
- 不要运行来源不可信的 YAML；
- 应人工检查所有路径；
- 检查 task、训练集和验证集映射；
- 检查 energy/forces/stress target；
- 检查 checkpoint 输出目录。

## 15. 启动 UMA 微调

### 15.1 使用模板默认运行

```bash
fairchem -c /path/to/lmdb/uma_sm_finetune_template.yaml
```

默认模板一般配置为单 GPU。

### 15.2 使用 Hydra 命令行覆盖

```bash
fairchem \
  -c /path/to/lmdb/uma_sm_finetune_template.yaml \
  epochs=20 \
  lr=1e-4 \
  batch_size=2 \
  job.run_dir=/path/to/surface_finetune/runs \
  +job.timestamp_id=zno_surface_v1
```

### 15.3 建议的第一轮超参数

建议以以下范围做小规模比较：

```text
base model: uma-s-1p2
learning rate: 4e-4, 2e-4, 1e-4, 5e-5
epochs: 5–30
batch size: 1–8，取决于显存和体系原子数
max_neighbors: 300，显存不足时可测试 100
```

官方配置指出：

- `max_neighbors=300` 是 UMA 原始训练的常用值；
- 显存不足时 `100` 通常可作为折中；
- batch size 应尽量充分利用显存；
- 但不能大到每个 epoch 只有很少优化步。

### 15.4 不要照搬 MACE 学习率

MACE-Osaka26 从头训练使用：

```text
lr = 0.005
```

UMA 微调官方模板大约使用：

```text
lr = 4e-4
```

个人小数据微调通常还可从：

```text
1e-4 或 2e-4
```

开始。学习率太大可能快速破坏预训练知识并导致灾难性遗忘。

## 16. 多 GPU 和恢复训练

### 16.1 本地多 GPU

修改：

```yaml
job:
  scheduler:
    mode: LOCAL
    ranks_per_node: 2
    num_nodes: 1
```

其中 `ranks_per_node` 通常对应每节点使用的 GPU 数量。

### 16.2 Slurm 多节点

```yaml
job:
  scheduler:
    mode: SLURM
    ranks_per_node: 4
    num_nodes: 2
```

多节点训练的 `run_dir` 必须位于所有节点可访问的共享文件系统。

### 16.3 恢复训练

FAIRChem 会为 checkpoint 保存恢复配置。一般可使用：

```bash
fairchem -c /path/to/checkpoints/final/resume.yaml
```

恢复前检查：

- checkpoint 是否来自同一模型；
- task 是否相同；
- 数据集路径是否仍有效；
- batch size 和 GPU 数是否改变；
- 是否真的希望继续优化，而不是从最佳 checkpoint 开始新实验。

## 17. 微调后加载模型

官方加载方式类似：

```python
from fairchem.core.units.mlip_unit import load_predict_unit
from fairchem.core import FAIRChemCalculator

predictor = load_predict_unit(
    "/path/to/runs/checkpoints/final/inference_ckpt.pt"
)

calc = FAIRChemCalculator(
    predictor,
    task_name="oc25",
)
```

最重要的规则：

> 推理必须使用与微调相同的 task。

例如：

```text
微调 task = oc25
推理 task = oc25
```

不能在 `oc25` 微调后任意改成：

```text
omat
oc22
omol
```

因为 task 参与 UMA 的 MoLE 路由和能量定义。

## 18. 微调前的基线测试

在训练前，必须先记录原始 UMA 的表现。否则无法判断微调是否真正改善。

建议测试：

- ZnO 体相晶格常数；
- 体相能量和力；
- ZnO 不同表面的结构弛豫；
- 表面能；
- H₂O 多个位点吸附；
- H₂O 吸附能；
- 2-壬酮多个构型吸附；
- 缺陷形成能；
- 短时间 300 K MD；
- 高温稳定性；
- 反应路径或解离趋势。

建议记录：

```text
energy MAE        eV/atom
energy RMSE       eV/atom
force MAE         eV/Å
force RMSE        eV/Å
stress MAE        GPa
adsorption error  eV
surface energy error
bond-length error Å
angle error       degree
MD stability
```

## 19. 不能只看训练 loss

一个适合表面模拟的模型必须通过多层验证。

### 19.1 标签误差

检查：

- 每原子能量 MAE/RMSE；
- 原子力 MAE/RMSE；
- 最大力误差；
- 不同元素的力误差；
- 表面原子与体相原子的分组误差；
- 吸附物原子的力误差；
- 应力误差。

### 19.2 物性误差

检查：

- 晶格常数；
- 表面能；
- 吸附能；
- 缺陷形成能；
- 解离能；
- 反应能；
- 过渡态相对能量。

### 19.3 结构优化

比较：

- 最终吸附位点；
- 键长；
- 键角；
- 吸附高度；
- 表面重构；
- 最大残余力；
- 是否收敛到 DFT 相同极小点。

### 19.4 分子动力学

检查：

- 温度稳定性；
- 总能量漂移；
- 非物理解离；
- 原子重叠；
- 吸附物异常脱附；
- 表面坍塌；
- 长时间稳定性；
- 径向分布或构象统计。

## 20. 吸附能专项验证

吸附能应使用一致参考：

\[
E_\mathrm{ads}
=E_{\mathrm{slab+ads}}
-E_{\mathrm{slab}}
-E_{\mathrm{adsorbate}}
\]

验证时，对 DFT 和 UMA 分别计算完整公式，不能把 DFT 的某一参考项与 UMA 的
另一参考项混用。

应测试：

- 不同位点的绝对吸附能；
- 位点相对能量排序；
- 分子吸附与解离吸附排序；
- 覆盖度依赖；
- slab 厚度依赖；
- 真空层依赖；
- 不同构象间能量差。

对于实际研究，正确的相对排序有时比极低的总能量 MAE更重要。

## 21. 防止灾难性遗忘

如果只用少量 ZnO 表面数据对 UMA 全参数微调，可能出现：

- ZnO 表面精度提高；
- 体相精度下降；
- 气相分子精度下降；
- 未见过表面的泛化能力下降；
- 原始通用能力被破坏。

降低风险的方法：

### 21.1 使用较小学习率

优先测试：

```text
2e-4
1e-4
5e-5
```

### 21.2 使用提前停止

根据独立验证集选择 checkpoint，不要只使用最后一个 epoch。

### 21.3 保留 replay 数据

可加入少量与目标领域相关但更广泛的数据：

- ZnO 体相；
- 气相 H₂O；
- 气相有机分子；
- 其他 ZnO 晶面；
- 没有吸附物的 clean slab；
- 不同表面缺陷。

### 21.4 同时评估多个子集

每轮训练后分别报告：

```text
bulk
clean surface
defect
adsorption
gas molecule
reaction
MD frames
```

不要只报告全部数据混合后的一个平均 MAE。

### 21.5 保存所有重要 checkpoint

至少保存：

- 原始 UMA；
- 第一次微调模型；
- 每轮主动学习模型；
- 验证集最佳模型；
- 最终发布模型；
- 训练配置；
- 数据集校验和。

## 22. 主动学习闭环

最推荐的长期方案不是一次性生成巨大数据集，而是反复执行：

```text
初始模型
   ↓
运行表面结构优化/MD/吸附搜索
   ↓
发现不确定、异常或模型分歧大的结构
   ↓
去重与多样性筛选
   ↓
DFT 标注
   ↓
加入训练集
   ↓
重新微调
   ↓
独立测试
```

### 22.1 候选结构来源

- 原始 UMA 结构优化轨迹；
- 微调 UMA 的 MD；
- 高温 MD；
- 多吸附位点搜索；
- NEB；
- 缺陷生成；
- 表面重构搜索；
- 扫描吸附高度；
- 人工施加扰动。

### 22.2 选择最有价值的数据

可优先选择：

- ensemble 模型力分歧大的结构；
- UMA 与 DFT 误差大的结构；
- 原子力特别大的结构；
- 模型出现非物理行为前的结构；
- 与已有训练集描述符距离较大的结构；
- 新晶面、新缺陷或新反应类别；
- 对目标物性影响最大的结构。

### 22.3 建议迭代次数

通常 3–5 轮主动学习就可能明显改善目标领域表现：

```text
v0: 原始 UMA
v1: 初始表面数据
v2: 补充优化/MD 失败构型
v3: 补充反应和缺陷
v4: 补充外推测试失败构型
```

每一轮都必须使用同一份固定测试集比较，不能不断把测试集加入训练集后继续
声称测试性能提高。

## 23. 推荐的第一版 ZnO 项目

### 23.1 目标

第一版可限定为：

```text
ZnO (10-10) 表面
H2O 吸附
2-壬酮吸附
300 K 表面 MD
```

不要第一轮就覆盖所有 ZnO 晶面、所有有机分子和所有反应。

### 23.2 DFT 设置

如果选择 `oc25`，建议尽量统一：

```text
VASP
RPBE+D3
一致 PAW 数据集
一致 ENCUT
一致 k 点密度
表面偶极修正
一致电子收敛
一致自旋策略
```

如果选择 `oc22`：

```text
VASP
PBE+U
统一 U 值
统一自旋极化设置
统一赝势
```

### 23.3 初始训练数据

可包含：

```text
ZnO bulk:                    50–100
clean (10-10) slab:        100–200
surface perturbations:     100–200
oxygen/zinc vacancies:     100–200
H2O adsorption:            300–500
2-nonanone adsorption:     300–500
optimization intermediates:200–400
AIMD frames:               300–800
repulsive/reaction data:    50–150
```

### 23.4 第一轮微调参数

建议起点：

```text
base_model_name: uma-s-1p2
uma_task: oc25
regression_task: ef
learning_rate: 1e-4 或 2e-4
epochs: 10–30
batch_size: 由显存决定
max_neighbors: 300
```

如果训练应力：

```text
regression_task: efs
```

### 23.5 第一轮验收条件

第一轮不应只要求 validation loss 下降，还应要求：

- 独立测试集 force MAE 改善；
- 吸附能误差改善；
- 吸附位点排序正确；
- 表面结构不坍塌；
- 300 K 短 MD 稳定；
- 没有比原始 UMA 更严重的非物理解离；
- 体相和气相参考没有明显退化。

## 24. 推荐的目录结构

可在 `/home/user/wu_test` 下建立：

```text
uma_surface_project/
├── README.md
├── configs/
│   ├── dft_settings.md
│   └── uma_finetune.yaml
├── data/
│   ├── raw/
│   ├── processed/
│   ├── train/
│   ├── val/
│   ├── test/
│   └── lmdb/
├── metadata/
│   ├── structures.csv
│   ├── dft_provenance.json
│   └── dataset_checksums.txt
├── scripts/
│   ├── collect_dft.py
│   ├── validate_extxyz.py
│   ├── split_by_group.py
│   ├── create_lmdb.sh
│   ├── train.sh
│   └── evaluate.py
├── runs/
│   ├── baseline/
│   ├── finetune_v1/
│   └── finetune_v2/
└── reports/
    ├── baseline.md
    ├── finetune_v1.md
    └── final_validation.md
```

## 25. 数据审计清单

训练前逐项确认：

```text
[ ] 所有结构可由 ASE 读取
[ ] 元素、坐标和晶胞正确
[ ] PBC 标记正确
[ ] energy 单位为 eV
[ ] forces 单位为 eV/Å
[ ] stress 单位和符号正确
[ ] 不存在 NaN 或 Inf
[ ] 不存在明显原子重叠
[ ] DFT 全部正常收敛
[ ] 泛函和色散设置统一
[ ] 赝势和 U 值统一
[ ] clean slab 和 adsorbate 参考齐全
[ ] 相邻轨迹帧没有跨 train/val/test 泄漏
[ ] train/val/test 按物理体系分组
[ ] 测试集从未参与训练选择
[ ] 数据集版本和校验和已记录
```

## 26. 训练审计清单

```text
[ ] 使用预期的 uma-s-1p2 checkpoint
[ ] UMA task 设置正确
[ ] regression task 设置正确
[ ] 训练和推理 task 相同
[ ] 学习率没有照搬 MACE 的 0.005
[ ] batch size 与显存匹配
[ ] 训练 loss 正常下降
[ ] validation loss 没有持续上升
[ ] 保存最佳 checkpoint
[ ] 保存完整 YAML
[ ] 保存软件版本
[ ] 保存随机种子
[ ] 记录 GPU 和训练时长
```

## 27. 模型验收清单

```text
[ ] 独立 energy MAE/RMSE
[ ] 独立 force MAE/RMSE
[ ] 分元素力误差
[ ] 表面原子力误差
[ ] 吸附物原子力误差
[ ] 表面能
[ ] 吸附能
[ ] 缺陷形成能
[ ] 位点能量排序
[ ] 几何优化终态
[ ] 300 K MD 稳定性
[ ] 高温短 MD 稳定性
[ ] 未见晶面外推测试
[ ] 与原始 UMA 对比
[ ] 检查灾难性遗忘
```

## 28. 常见错误

### 28.1 把不同 DFT 水平直接混合

这是最常见且最严重的问题之一。解决方法是统一 DFT，或明确进行多保真能量
对齐；个人第一版项目不建议直接做复杂多保真训练。

### 28.2 只使用最低能结构

会导致模型只认识极小点，不认识优化路径和 MD 构型。必须加入力、扰动结构、
优化中间帧和 AIMD。

### 28.3 相邻 AIMD 帧随机拆分

会造成验证集泄漏。必须按完整轨迹划分。

### 28.4 微调 task 与推理 task 不一致

会改变 UMA 路由，结果没有可靠物理意义。

### 28.5 学习率过大

可能迅速破坏预训练权重。应从 `1e-4` 或 `2e-4` 等较小值开始比较。

### 28.6 只看平均能量 MAE

平均能量误差可能被大量简单结构主导。还需检查力、吸附能、缺陷、结构优化和
MD。

### 28.7 训练集数量大但高度重复

一万帧同一条平稳 AIMD 轨迹，可能不如一千个覆盖不同位点、缺陷和反应区域的
结构。

### 28.8 忽略气相和 clean slab 参考

会导致吸附能系统偏差难以诊断。

### 28.9 没有短程排斥数据

模型可能在 MD 中访问异常短距离并产生不稳定力。应加入少量合理的排斥区
构型。

## 29. 最终推荐路线

针对当前 ZnO 表面、H₂O 和有机分子吸附研究，推荐路线为：

```text
1. 使用原始 uma-s-1p2 建立基线

2. 在 oc22 和 oc25 中根据 DFT 设置选择一个
   - PBE+U 氧化物：oc22
   - RPBE+D3 表面/吸附：oc25

3. 统一 DFT 设置

4. 构建以下数据：
   - ZnO bulk
   - clean surface
   - defects
   - H2O adsorption
   - organic adsorption
   - distorted configurations
   - optimization trajectories
   - AIMD
   - repulsive/reaction configurations

5. 按轨迹和物理体系划分 train/val/test

6. 转换为 ASE-LMDB

7. 使用 uma-s-1p2 单任务微调

8. 比较：
   - energy
   - forces
   - adsorption energy
   - structure relaxation
   - MD stability

9. 使用主动学习补充失败构型

10. 重复 3–5 轮
```

这条路线比模仿 MACE-Osaka26、从零重训一个通用 UMA 更现实，也更适合个人
GPU 资源。

## 30. 参考资料

- MACE-Osaka26 仓库：  
  <https://github.com/qiqb-osaka/mace-osaka26>

- MACE-Osaka26 训练脚本：  
  <https://github.com/qiqb-osaka/mace-osaka26/blob/main/mace_osaka26/mace-osaka26-small.sh>

- FAIRChem 仓库：  
  <https://github.com/facebookresearch/fairchem>

- UMA 模型和 task 说明：  
  <https://fair-chem.github.io/uma/>

- FAIRChem UMA 微调指南：  
  <https://github.com/facebookresearch/fairchem/blob/main/docs/core/common_tasks/fine_tuning.md>

- UMA Hugging Face 模型：  
  <https://huggingface.co/facebook/UMA>

- UMA 论文：  
  <https://arxiv.org/abs/2506.23971>

