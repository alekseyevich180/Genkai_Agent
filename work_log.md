# 工作日志索引

本文件只作为日志入口，不再保存完整工作记录。每日具体日志放在 `work_logs/` 目录中。

## 当前恢复入口（SAGE 分支）

- 2026-11-24：表面建模包按职责拆成子包（`mlip/`、`builders/`、`screening/`、`app/`），旧模块路径保留为转发模块；
  指南移到 `docs/guides/`，`ptomodel_mapping.md` 移到 `docs/`。同日较早：CUDA UMA 的 `oom_fallback`、
  共享 Periodic GP 采样器（`search_sampler.py`）及非晶 TiO2 表面五方法对照（Slurm 240）。
  同日新增 `amorphous_bulk`：晶体经 MLIP 熔融-淬火得到非晶块体，可串联 `amorphous_slab` 切表面。
  详见 [2026-11-24](work_logs/2026-11-24.md)。
- 2026-11-18：服务器作业 214 检查（SnO2(110) 弛豫 PASS）、顶部五个任务改为单作业串行（作业 216），
  旧 UMA 测试脚本和输出归档到 `/home/wu/start/test/`、`/home/wu/output/test/`。
  详见 [2026-11-18](work_logs/2026-11-18.md)。
- 2026-11-17：接入本机独立安装的 MACE / UMA，统一各能量入口、增加启动脚本与接口文档；
  两个环境离线测试通过，模拟冒烟 PASS 27 / WARN 1 / FAIL 0 / SKIP 1，两个 Cu 原胞 GPU 单点通过。
  详见 [2026-11-17](work_logs/2026-11-17.md)。
- 2026-11-17：进一步完成面向普通使用者的 `genkai.yaml` 配置、统一 MLIP YAML 任务入口、
  不安装 MLIP 的引导安装与独立项目依赖环境；本机实际安装与重复配置通过，
  最终离线测试 166 passed / 1 skipped，详见同日日志“后续：面向普通使用者的配置化安装与任务入口”。
- 2026-11-16：创建 `SAGE` 分支（只含建模 + MLIP 筛选）和 `install.sh`，见 [2026-11-16](work_logs/2026-11-16.md)
  的“创建 SAGE 分支”。

## main 分支的历史（SAGE 创建前）

以下条目来自 `main`。其中提到的 `genkai-workflow`、`docs/daily-agent-work-guide.md` 等只存在于 `main`；
文中的 `scripts/...` 路径指 Skill 薄入口，稳定实现现在在 `src/genkai/modeling/surface/` 的子包里。

- 2026-11-13：`feat/genkai-evolution` 已并入 `main`，形成检查点 tag
  `sage-checkpoint-0`，详见 [2026-11-13](work_logs/2026-11-13.md)。`main` 是唯一开发
  分支。
- 2026-11-13：SAGE 第一步 structure-only 执行器已实现
  （`genkai-workflow surface execute`，2026-08-05 计划 Task 2），见
  [2026-11-13](work_logs/2026-11-13.md) 的“SAGE 第一步”。当前方向是构建复杂表面
  （暂不考虑吸附），从同一日志的“复杂表面构建：可用脚本与库盘点”开始；继续前按
  Agent 简单日常工作指南（`docs/daily-agent-work-guide.md`，只在 main 上） 准备单任务说明，
  不直接扩大到网络、LLM 或科学计算。
- 2026-11-16：查询了空位、预吸附 O/OH/H2O、贵金属团簇、SAM 四类组件的位置与缺口，
  并把 `AGENTS.md` 中的测试基线更新为实测结果，见 [2026-11-16](work_logs/2026-11-16.md)。
  约定：每次工作同步更新 `AGENTS.md`。
- 2026-11-16：已实现 SAM 构建器（`scripts/sam/sam_builder.py`）和 ALD 非晶覆盖层构建器
  （`scripts/ald/ald_overlayer.py`），见同日日志“SAM 与 ALD 复杂表面脚本：实现”。下一步是
  把 SAM 注册进 structure-only 执行器。
- 2026-11-16：新增 `scripts/run_modeling_smoke.py`，用仓库已有结构跑全部建模方式
  （本机 PASS 18 / WARN 1 / FAIL 0 / SKIP 2），见同日日志“表面建模冒烟测试脚本”。
- 2026-11-16：新增纯非晶表面（`scripts/amorphous/amorphous_slab.py`）；ALD 全覆盖膜无法晶格匹配时
  改为切割并修复接缝；c 轴倾斜的旧 slab 自动规范化。冒烟 26 个用例 PASS 23 / WARN 1 /
  FAIL 0 / SKIP 2，见同日日志“非晶部分改进”。
- 2026-11-16：测试脚本控制命令（冒烟全部 / 只测非晶 / pytest / 手动生成）速查见同日日志“测试脚本控制命令（速查）”。
- 2026-11-16：MLIP 筛选层：`calculators.py`、SAM 能量搜索（`scripts/sam/sam_search.py`）、
  非晶表面和界面筛选（`scripts/amorphous/amorphous_screen.py`）、团簇搜索的倾斜、输入形状和真空加高，
  旧脚本自动固定底层。仅用模拟计算器验证，未运行 UMA。见同日日志“MLIP 筛选层实现”。
- 2026-11-16：给其他使用者的入口 `genkai-surface`（YAML 任务文件，只生成结构）、使用手册
  `docs/surface-modeling-user-guide.md` 和示例 `examples/surface_jobs/`；冒烟 31 个用例 PASS 29 / WARN 1 /
  SKIP 1。见同日日志“给其他使用者的建模入口”。

## 日志文件

- [2026-06-29](work_logs/2026-06-29.md)
- [2026-06-30](work_logs/2026-06-30.md)
- [2026-07-01](work_logs/2026-07-01.md)
- [2026-07-02](work_logs/2026-07-02.md)
- [2026-07-06](work_logs/2026-07-06.md)
- [2026-07-07](work_logs/2026-07-07.md)
- [2026-07-08](work_logs/2026-07-08.md)
- [2026-07-09](work_logs/2026-07-09.md)
- [2026-07-10](work_logs/2026-07-10.md)
- [2026-07-15](work_logs/2026-07-15.md)
- [2026-07-17](work_logs/2026-07-17.md)
- [2026-07-23](work_logs/2026-07-23.md)
- [2026-07-28](work_logs/2026-07-28.md)
- [2026-07-30](work_logs/2026-07-30.md)
- [2026-08-03](work_logs/2026-08-03.md)
- [2026-08-04](work_logs/2026-08-04.md)
- [2026-08-05](work_logs/2026-08-05.md)
- [2026-08-31](work_logs/2026-08-31.md)
- [2026-11-12](work_logs/2026-11-12.md)
- [2026-11-13](work_logs/2026-11-13.md)
- [2026-11-16](work_logs/2026-11-16.md)
- [2026-11-17](work_logs/2026-11-17.md)
- [2026-11-18](work_logs/2026-11-18.md)
- [2026-11-24](work_logs/2026-11-24.md)

## 相关长期文档

- [AGENTS.md](AGENTS.md)：在 SAGE 分支上工作的规则、目录结构和与 main 的同步方法。
- [docs/surface-modeling-user-guide.md](docs/surface-modeling-user-guide.md)：给使用者的建模手册。
- [docs/mlip-interfaces.md](docs/mlip-interfaces.md)：MACE / UMA 接口与独立环境调用。
- [docs/artifact-contracts.md](docs/artifact-contracts.md)：artifact 与运行清单契约。
- [docs/ptomodel_mapping.md](docs/ptomodel_mapping.md)：论文字段到建模任务参数的映射说明。
- [docs/guides/](docs/guides/)：UMA 表面知识微调、开源大模型本地安装两份操作指南。
- `plan.md`、`GENKAI_EVOLUTION_PLAN.md` 只在 `main` 上。

## 维护约定

- `work_logs/YYYY-MM-DD.md`：记录当天实际完成的工作、修改文件、验证结果和遗留问题。
- `work_log.md`：只更新索引，不写长篇日志正文。
