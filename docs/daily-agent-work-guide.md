# Agent 简单日常工作指南

本指南根据 `work_logs/2026-08-05.md` 的恢复入口整理，并使用当前 Harness 命令替代
日志中的旧执行方式。每天只推进一个可独立验证的小任务；默认不启动网络或科学计算。

## 今日推荐任务

只完成 8 月 5 日计划的 Task 1：为
`src/genkai/modeling/surface/adsorbate.py` 增加稳定的程序化 API。

目标接口：

```python
run_adsorbate_landscape(
    config: AdsorbateLandscapeConfig,
) -> AdsorbateLandscapeResult
```

验收条件：

- `AdsorbateLandscapeResult.structure_paths` 按生成顺序返回候选 CIF；
- 返回的结构文件存在并可被 ASE 读取；
- `main()` 只负责解析 CLI 参数和调用程序化 API；
- 现有 CLI 参数与 Skill 薄入口保持兼容；
- 测试固定使用 `calculator="none"` 和 `max_steps=0`；
- mock energy 只作为工作流测试值，不能称为吸附能或科学结果。

## 1. 开始工作

从项目根目录执行：

```bash
cd /home/pj24001724/ku40000345/wu/Genkai_Evolution
source .venv/bin/activate
git status --short --branch
python scripts/check_harness.py doctor
python scripts/check_harness.py quick
```

开始修改前阅读：

```text
AGENTS.md
work_logs/2026-08-05.md
src/genkai/modeling/surface/adsorbate.py
tests/modeling/test_surface_algorithm_ownership.py
```

如果发现用户已有修改，保留它们，不执行 reset、checkout 或批量格式化。

## 2. 先写失败测试

创建：

```text
tests/modeling/test_adsorbate_programmatic_api.py
```

测试至少证明：

1. 使用最小 slab 和 H2 fixture；
2. 显式设置 `site_symbols="Sn"`；
3. 覆盖数只使用 `1`；
4. pattern 只使用少量确定性组合；
5. `calculator="none"`、`max_steps=0`、固定 seed；
6. 返回的每个 `structure_path` 都存在且可被 ASE 读取。

运行：

```bash
python -m pytest \
  tests/modeling/test_adsorbate_programmatic_api.py \
  -q --tb=short
```

第一次应因为程序化 API 尚不存在而失败。保存失败原因，不通过放宽断言绕过它。

## 3. 实施最小改动

只修改：

```text
src/genkai/modeling/surface/adsorbate.py
tests/modeling/test_adsorbate_programmatic_api.py
```

实施顺序：

1. 增加不可变的 `AdsorbateLandscapeConfig`；
2. 增加不可变的 `AdsorbateLandscapeResult`；
3. 把 `main()` 中参数解析后的业务逻辑移入 `run_adsorbate_landscape()`；
4. 让 `main()` 将 CLI 参数转换成 config，再调用新 API；
5. 不使用修改 `sys.argv` 或 subprocess 自调用的方式复用 CLI；
6. 不在本任务中新增 structure-only executor、workflow 参数或 JSONL 修复。

## 4. 验证

先运行目标测试：

```bash
python -m pytest \
  tests/modeling/test_adsorbate_programmatic_api.py \
  tests/modeling/test_surface_algorithm_ownership.py \
  tests/compatibility/test_paperread_surface.py \
  -q --tb=short
```

然后运行 Harness：

```bash
python scripts/check_harness.py quick
python -m genkai.modeling.surface.adsorbate --help
git diff --check
git status --short
git diff --stat
```

如果公共入口、package data 或所有权发生变化，再升级运行：

```bash
python scripts/check_harness.py ci
python scripts/check_harness.py package
```

完整测试当前仍有 `tests/test_structure_builder.py` 的既有收集阻塞。局部测试通过不能写成
“完整测试通过”。

## 5. 必须停止的情况

出现以下情况时停止并报告，不继续猜测：

- 测试需要在线 LLM 或 Materials Project；
- 需要把论文中的 HRTEM `(101)` 自动当作 exposed facet；
- 需要猜测 molecule、coverage、site symbols 或 SAM 锚定构型；
- 代码开始调用 UMA、MACE、DeepMD、VASP、GPU/PJM、训练或 MD；
- `calculator="none"` 无法继续，必须产生真实能量或结构弛豫；
- 修改范围扩展到 Task 2 的 executor 或 Task 3 的 workflow/CLI 接入。

## 6. 收尾和日志

完成后在当天 `work_logs/YYYY-MM-DD.md` 记录：

- 实际修改的文件；
- 失败测试和修复后测试的命令与结果；
- 生成的测试结构数量；
- `calculator=none` 和 `max_steps=0`；
- 未运行的网络、LLM 和科学计算；
- 仍存在的 blocker 和下一恢复入口。

只有用户明确要求时才 commit、push 或创建 PR。

## 可直接交给 Agent 的任务

```text
读取 AGENTS.md、docs/daily-agent-work-guide.md 和 work_logs/2026-08-05.md。

今天只完成 Task 1：为 adsorbate.py 增加稳定程序化 API。
先检查 git status 和当前实现，再写失败测试，实施最小修改并运行指南中的目标验证。

固定使用 calculator=none、max_steps=0，不访问网络、LLM、Materials Project，不运行
VASP、MLIP、GPU/PJM、训练或 MD。不要开始 Task 2。最后更新当天工作日志，并报告
实际命令、结果、未验证内容和残余风险。
```
