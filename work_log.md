# 工作日志索引

本文件只作为日志入口，不再保存完整工作记录。每日具体日志放在 `work_logs/` 目录中。

## 当前恢复入口

- 2026-11-13：`feat/genkai-evolution` 已并入 `main`，形成检查点 tag
  `sage-checkpoint-0`，详见 [2026-11-13](work_logs/2026-11-13.md)。`main` 是唯一开发
  分支。
- 2026-11-13：SAGE 第一步 structure-only 执行器已实现
  （`genkai-workflow surface execute`，2026-08-05 计划 Task 2），见
  [2026-11-13](work_logs/2026-11-13.md) 的“SAGE 第一步”。当前方向是构建复杂表面
  （暂不考虑吸附），从同一日志的“复杂表面构建：可用脚本与库盘点”开始；继续前按
  [Agent 简单日常工作指南](docs/daily-agent-work-guide.md) 准备单任务说明，
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
- 2026-11-16：创建并推送 `SAGE` 分支（只含建模 + MLIP 筛选，带 `install.sh`；CI 通过），见同日日志“创建 SAGE 分支”。

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

## 相关长期文档

- [plan.md](plan.md)：paperread 表面研究建模、经验抽取与 Agent skill 闭环计划。
- [GENKAI_EVOLUTION_PLAN.md](GENKAI_EVOLUTION_PLAN.md)：library-first
  artifact、workflow、skill 与 Agent 架构演进计划，以及当前实施快照和下一阶段
  目录结构收敛入口。

## 维护约定

- `work_logs/YYYY-MM-DD.md`：记录当天实际完成的工作、修改文件、验证结果和遗留问题。
- `plan.md`：记录长期研究计划、架构提案、阶段路线和实施标准。
- `work_log.md`：只更新索引，不写长篇日志正文。
