# 使用方法 / Manual

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

在仓库根目录执行：

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

## 3. 初始化项目路径

安装后，需要告诉命令行工具项目根目录在哪里。先确认已经激活项目虚拟环境：

```bash
cd /home/pj24001724/ku40000345/wu/Genkai_Agent
source .venv/bin/activate
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
```

如果子智能体需要使用不同模型，可以在对应子智能体目录下单独创建 `.env` 覆盖默认配置。

## 5. 启动 Web UI

推荐使用项目脚本一次性启动 ADK API Server、FastAPI 中间层和 Vite 前端：

```bash
source .venv/bin/activate
bash start/start_agent.sh
```

脚本会启动以下服务：

- ADK API Server：`http://localhost:8000`
- FastAPI 中间层：`http://localhost:8001`
- Vite 前端：`http://localhost:5173`

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

限制最大轮数：

```bash
agent run -p "Build a silicon FCC structure" --max-turns 20
```

使用 Flash 模式直接执行：

```bash
agent run -p "Build a silicon FCC structure" --flash
```

## 7. Know-Do Graph

Agent 使用 `know-do-graph` 统一存储 durable knowledge 和 working memory。

### 存储位置

```text
agents/Agent/.adk/know_do_graph.db
```

### 迁移来源

- `.adk/know_do_graph.db`
- `.adk/skill_graph.db`
- `.adk/memory_graph.db`
- `.adk/memory/*.json`
- `MEMORY.md`

### 常用命令

```bash
agent knowledge migrate 
#旧数据迁移进新的统一知识图数据库里。它会导入旧的 skill_graph.db、memory_graph.db、旧 JSON memory、MEMORY.md 等，转成统一know_do_graph.db

agent knowledge seed  #项目里的 skills 和 guides 写入知识图，作为“可检索的能力/流程节点”

agent knowledge stats #查看当前知识图的统计信息，比如节点数、边数、memory 数量等，用来检查知识库是否正常。

agent knowledge distill --min-evidence 3 
#把多次重复出现、证据足够的 working memory 提炼成更稳定的 durable knowledge。--min-evidence 3 表示至少需要 3 份相似/重复证据才考虑提升。
```

### 运行规则

- Skills are durable capability entries.
- Guides are durable procedure entries.
- Agent saves are native memory nodes.
- Retrieved memory and durable knowledge share one graph and one database.
