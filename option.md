# Genkai Agent 使用指南

Genkai Agent 是面向计算材料科学任务的技能型智能体平台，重点支持机器学习力场（MLFF）的生成与应用。它通过 `agents/Agent/skills/` 中的技能扩展能力，并可在运行过程中积累经验、调用工具、生成文件和保存会话产物。

## 1. 环境要求

- Linux 或 WSL Linux 环境
- Python 3.12 或更高版本
- `uv` Python 包管理工具
- 如需使用 Web UI，还需要 Node.js、npm 和 Vite 前端依赖

推荐在 WSL 中使用 `pipx` 安装 `uv`，避免污染系统 Python 环境：

```bash
sudo apt update && sudo apt install pipx -y
pipx ensurepath
pipx install uv
```

安装完成后，重新打开终端，确认命令可用：

```bash
uv --version
```

## 2. 安装 Genkai Agent

在 `Genkai_Agent` 仓库根目录执行：

```bash
uv venv .venv --python 3.12
source .venv/bin/activate
uv pip install -e .
uv pip install pytest
```

如果需要使用 Web UI，继续安装前端依赖：

```bash
cd web/vite-frontend
npm install
cd ../..
```

如本机尚未安装 Node.js，推荐通过 NVM 安装：

```bash
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash
source ~/.bashrc
nvm install 22
nvm use 22
nvm alias default 22
node -v
npm -v
```

## 3. 初始化项目路径

安装后，需要告诉命令行工具项目根目录在哪里。先确认已经激活项目虚拟环境：

```bash
cd /home/pj24001724/ku40000345/wu/Genkai_Agent
source .venv/bin/activate
```

激活后确认 `agent` 命令可用：

```bash
which agent
agent --help
```

正常情况下，`which agent` 应指向当前仓库下的 `.venv/bin/agent`，例如：

```text
/home/pj24001724/ku40000345/wu/Genkai_Agent/.venv/bin/agent
```

然后执行初始化：

```bash
agent init .
```

也可以指定绝对路径：

```bash
agent init /home/pj24001724/ku40000345/wu/Genkai_Agent
```

该命令会写入 `~/.agent/config.yaml`，保存 `project_root` 路径，使 Agent 即使被安装到 Python 环境中，也能正确找到 `agents/` 目录。

如果尚未激活虚拟环境，直接运行 `agent init ...` 可能出现：

```text
bash: agent: コマンドが見つかりません
```

这表示当前 shell 的 `PATH` 中找不到 `agent` 可执行文件，不代表仓库没有安装。先执行：

```bash
source .venv/bin/activate
```

或直接使用完整路径：

```bash
.venv/bin/agent init /home/pj24001724/ku40000345/wu/Genkai_Agent
```

注意：如果某个旧版本没有提供 `agent init` 子命令，可以直接使用 `AGENT` 环境变量指定项目根目录：

```bash
export AGENT=/home/pj24001724/ku40000345/wu/Genkai_Agent
```

也可以手动创建配置文件：

```yaml
project_root: /home/pj24001724/ku40000345/wu/Genkai_Agent
```

配置文件路径为：

```text
~/.agent/config.yaml
```

## 4. 配置模型与运行环境

首次运行前，创建 `agents/Agent/.env` 文件：

```bash
touch agents/Agent/.env
```

可参考以下内容配置模型、API、知识图谱数据库和技能相关环境变量：

```env
LLM_MODEL="MODEL_TYPE"
GRAPH_AGENT_MODEL="MODEL_TYPE"
REVIEW_AGENT_MODEL="MODEL_TYPE"
LLM_API_KEY="API_KEYS"
LLM_BASE_URL="BASE_URL"
KDG_DB_PATH="agents/Agent/.adk/know_do_graph.db"
EMBEDDING_MODEL="EMBEDDING_MODEL_TYPE"
AGENT_AUTO_REVIEW=1
AGENT_REVIEW_TRIGGER_THRESHOLD=20
AGENT_REVIEW_BATCH_SIZE=5
AGENT_REVIEW_STRATEGY=auto

# 技能相关环境变量，按需配置
CGCNN_ROOT="user/cgcnn"
MATTERGEN_ENV="user/../.mattergen"
TAVILY_API_KEY=""
BOHRIUM_MAT_IMAGE=""
BOHRIUM_MAT_MACHINE=""
eval_reference="user/../reference_MP2020correction.gz"
mattersim_model="user/../mattersim-v1.0.0-5M.pth"
mattergen_model="user/../mattergen/checkpoints"
BOHRIUM_VASP_IMAGE=""
BOHRIUM_VASP_MACHINE=""
```

如果子智能体需要使用不同模型，可以在对应子智能体目录下单独创建 `.env` 覆盖默认配置。

## 5. 启动 Web UI

Web UI 支持执行图可视化、产物上传与下载、材料结构显示和科学绘图。推荐使用项目脚本一次性启动 ADK API Server、FastAPI 中间层和 Vite 前端：

```bash
source .venv/bin/activate
bash script/start_agent.sh
```

脚本会启动以下服务：

- ADK API Server：`http://localhost:8000`
- FastAPI 中间层：`http://localhost:8001`
- Vite 前端：`http://localhost:5173`

日志文件位于：

```bash
logs/api-server.log
logs/web-main.log
logs/vite.log
```

如果启动失败，可查看对应日志：

```bash
tail -f logs/api-server.log
tail -f logs/web-main.log
tail -f logs/vite.log
```

按 `Ctrl+C` 可以停止全部服务。

## 6. 非交互式 CLI 运行

不启动 Web 服务时，可以直接通过命令行执行单次任务。

查看 `run` 子命令帮助：

```bash
agent run --help
```

直接传入提示词：

```bash
agent run -p "Build a silicon FCC structure"
```

从文件读取提示词：

```bash
agent run -f prompt.txt
```

将回答保存到文件：

```bash
agent run -p "Build a silicon FCC structure" -o result.txt
```

输出完整 JSON 结果：

```bash
agent run -p "Build a silicon FCC structure" --output-format json -o result.json
```

指定工作目录：

```bash
agent run --workspace /data/my_workspace -p "Build a silicon FCC structure"
```

或通过环境变量指定：

```bash
MATCLAW_WORKSPACE=/data/my_workspace agent run -p "Build a silicon FCC structure"
```

限制最大轮数：

```bash
agent run -p "Build a silicon FCC structure" --max-turns 20
```

指定会话 ID：

```bash
agent run -p "Build a silicon FCC structure" --session-id test-session
```

使用 Flash 模式直接执行：

```bash
agent run -p "Build a silicon FCC structure" --flash
```

每次运行都会在 `<workspace>/sessions/<session-id>/` 下创建会话目录，Agent 生成的文件会保存在该目录中。

## 7. 帮助与命令速查

查看顶层帮助：

```bash
agent --help
```

也可以使用短参数：

```bash
agent -h
```

查看各子命令帮助：

```bash
agent web --help
agent api-server --help
agent run --help
agent knowledge --help
```

主要子命令：

- `agent web`：启动 ADK Web UI。
- `agent api-server`：启动 ADK API Server，通常供 Web 前端或中间层调用。
- `agent run`：非交互式执行单次任务。
- `agent knowledge`：查看和管理 Know-Do Graph 知识图谱。

`web` 和 `api-server` 常用参数：

```bash
agent web --host 127.0.0.1 --port 8000
agent web --reload-agents --reload
agent web --workspace /data/my_workspace
agent web --log-level debug
agent web --verbose
```

```bash
agent api-server --host 127.0.0.1 --port 8000
agent api-server --reload-agents --reload
agent api-server --workspace /data/my_workspace
agent api-server --log-level debug
agent api-server --verbose
```

知识图谱相关命令：

```bash
agent knowledge query "surface modeling" --top-k 15 --depth 2
agent knowledge search-skills "vasp relaxation" --top-k 5
agent knowledge related-skills "vasp" --top-k 5 --depth 2
agent knowledge stats
agent knowledge seed
agent knowledge migrate
agent knowledge distill --min-evidence 3 --stale-days 30
```

## 8. 旧式 ADK Web Server

也可以使用默认 ADK Web Server 启动 Agent 网络：

```bash
agent web
```

默认工作空间位于：

```text
agents/Agent/.workspace
```

其中会保存技能、记忆和运行产物等数据。

## 9. 技能目录

主要技能位于：

```text
agents/Agent/skills/
```

当前项目包含多类材料计算相关技能，例如：

- VASP、ABACUS、LAMMPS、DeepMD、DPDisp
- ASE 与 DeepMD 联用
- Mattersim、MatterGen、CGCNN 预测
- Materials Project 数据查询
- 原子结构生成与转换
- 表面建模、吸附构型、缺陷与纳米团簇建模
- 绘图、数据库和 Bohrium 远程任务提交

新增或修改技能时，通常应在对应技能目录中维护 `SKILL.md`、脚本和引用文件。

## 10. 自动化测试

先激活虚拟环境：

```bash
source .venv/bin/activate
```

运行基础导入测试：

```bash
python -m pytest tests/test_agent.py -v
```

运行 Know-Do Graph 相关测试：

```bash
python -m pytest \
  tests/test_kdg_memory.py \
  tests/test_kdg_extractor.py \
  tests/test_kdg_review_pipeline.py \
  tests/test_kdg_auto_review.py \
  -v
```

运行全部测试：

```bash
python -m pytest tests -v
```

## 11. 常见问题排查

如果 `agent` 命令不可用，先确认虚拟环境已激活：

```bash
source .venv/bin/activate
which agent
agent --help
```

如果仍然找不到命令，重新安装当前仓库到虚拟环境：

```bash
uv pip install -e .
```

也可以不依赖 shell 的 `PATH`，直接调用虚拟环境里的可执行文件：

```bash
.venv/bin/agent --help
.venv/bin/agent init /home/pj24001724/ku40000345/wu/Genkai_Agent
```

如果看到 `Error: No such command 'init'.`，说明当前安装的代码还没有 `init` 子命令，需要更新到包含 `src/agent/scripts/start_agent.py` 中 `init` 命令的版本，或重新执行 `uv pip install -e .`。

如果 Agent 找不到项目目录，优先检查 `AGENT` 环境变量：

```bash
export AGENT=/home/pj24001724/ku40000345/wu/Genkai_Agent
```

如果当前安装版本支持 `agent init`，也可以重新初始化：

```bash
agent init /home/pj24001724/ku40000345/wu/Genkai_Agent
```

如果 Web UI 无法打开，检查三个服务是否都已启动，并查看日志：

```bash
tail -f logs/api-server.log
tail -f logs/web-main.log
tail -f logs/vite.log
```

如果前端依赖缺失，重新安装：

```bash
cd web/vite-frontend
npm install
npm run dev
```

如果模型调用失败，检查 `agents/Agent/.env` 中的 `LLM_MODEL`、`LLM_API_KEY`、`LLM_BASE_URL` 是否正确，并确认所选模型服务可访问。

## 12. 当前任务 Checkpoint：paperread 外部库接入

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
