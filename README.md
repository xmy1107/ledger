# Ledger of Us

一个面向亲密关系事件记录、花费记账、AI 初步分析和关系事件图谱的本地 Web MVP。

## 当前 MVP

- 事件录入：日期、叙述者、标题、金额、情绪强度、正文、标签。
- 事件 DAG：每条事件可以关联到已有事件，后端保存为 `event_edges`。
- AI 初评：优先调用本机 Ollama；如果 Ollama 不可用，会退回到本地规则分析。
- 本地数据库：SQLite，默认写入 `data/ledger.db`。
- mem0 架构预留：`backend/memory.py` 中提供 mem0 可选适配层，后续安装 `mem0ai` 后可切换。

## 运行

使用 Codex 捆绑 Python 或本机 Python 运行：

```powershell
python backend/server.py
```

如果 PATH 里没有 Python，可以用 Codex 运行时：

```powershell
C:\Users\22061\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe backend/server.py
```

打开：

```text
http://127.0.0.1:8765
```

## Ollama 配置

默认会请求：

```text
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_MODEL=deepseek-r1
```

可在 PowerShell 中覆盖：

```powershell
$env:OLLAMA_MODEL="deepseek-r1:latest"
$env:OLLAMA_BASE_URL="http://127.0.0.1:11434"
```

## 后续路线

1. 双方独立输入：男方/女方分别维护叙述，AI 合并矛盾点和共同事实。
2. AI 判官：把事件、金额、变化量、承诺、边界侵犯、修复行为拆成可解释评分。
3. AI 心理师/调解师：分离“谁对谁错”和“关系模式诊断”。
4. 长上下文记忆：短期上下文走当前事件图，长期记忆走 mem0。
5. 微信导入：解析聊天记录、转账、图片 OCR、时间线重建，再让用户确认归档。
6. 图谱视图：从 DAG 扩展到“事件-承诺-金钱-情绪-人物状态”的多类型关系图。

