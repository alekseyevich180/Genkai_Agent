# 工作日志索引

本文件只作为日志入口，不再保存完整工作记录。每日具体日志放在 `work_logs/` 目录中。

## 当前恢复入口

- 2026-11-13：`feat/genkai-evolution` 已并入 `main`，形成检查点 tag
  `sage-checkpoint-0`，详见 [2026-11-13](work_logs/2026-11-13.md)。`main` 是唯一开发
  分支。
- 2026-11-13：SAGE 第一步 structure-only 执行器已实现
  （`genkai-workflow surface execute`，2026-08-05 计划 Task 2），见
  [2026-11-13](work_logs/2026-11-13.md) 的“SAGE 第一步”。下一步是空位 runner 和
  “空位表面 + 吸附”链式任务；继续前按
  [Agent 简单日常工作指南](docs/daily-agent-work-guide.md) 准备单任务说明，
  不直接扩大到网络、LLM 或科学计算。

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

## 相关长期文档

- [plan.md](plan.md)：paperread 表面研究建模、经验抽取与 Agent skill 闭环计划。
- [GENKAI_EVOLUTION_PLAN.md](GENKAI_EVOLUTION_PLAN.md)：library-first
  artifact、workflow、skill 与 Agent 架构演进计划，以及当前实施快照和下一阶段
  目录结构收敛入口。

## 维护约定

- `work_logs/YYYY-MM-DD.md`：记录当天实际完成的工作、修改文件、验证结果和遗留问题。
- `plan.md`：记录长期研究计划、架构提案、阶段路线和实施标准。
- `work_log.md`：只更新索引，不写长篇日志正文。
