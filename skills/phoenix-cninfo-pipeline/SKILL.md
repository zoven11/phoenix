---
name: phoenix-cninfo-pipeline
description: >
  编排从本地 PDF 或巨潮网公告检索/下载，到 Phoenix 文档结构化抽取、
  workspace 复用、自动迭代、评估和经验沉淀的完整流程。当用户给出本地
  PDF、要求下载巨潮公告、可选给出字段或 workspace，或者只要求 Phoenix
  自动完成文档抽取时使用。
metadata:
  openclaw:
    requires:
      bins:
        - python
        - agentic-extract
        - xdev
        - xdev-config
        - ppx
---

# Phoenix 巨潮公告流水线

当任务从本地 PDF 或巨潮网公告开始，并最终需要用 Phoenix 完成结构化抽取时，
使用本 skill 作为总协调层。

默认采用全自动流程。用户可以只提供一个文件路径。除非出现文档类型无法可靠
判断、多个 workspace 冲突、业务口径不清、模型/网络/权限失败等情况，不要一
开始就要求用户补充字段或确认 workspace。

所有路径示例都应视为占位符。实际执行时，优先从当前项目根目录或用户给出的
workspace 路径中自动解析，不要依赖某台机器上的固定绝对路径。

## 关联 Skill

1. `cninfo-announcement-fetch`：检索并下载巨潮网公告元数据和 PDF。
2. `phoenix`：运行 Phoenix、`agentic-extract`、`xdev run/eval`。
3. `phoenix-evolution`：复用历史场景、分析失败、沉淀经验。

## 总流程

1. 接收用户给出的最短输入：
   - 本地 PDF 路径
   - 巨潮网下载条件
   - 可选字段列表
   - 可选 workspace 名称或路径
2. 如果用户给了 PDF，直接使用该 PDF；如果没给 PDF，则用
   `cninfo-announcement-fetch` 下载公告。
3. 从文件名和正文判断文档类型。
4. 使用 `phoenix-evolution` 读取历史经验并查找可复用 workspace。
5. 如果找到高置信可复用 workspace，先用该 workspace 对 PDF 运行
   `xdev run`。
6. 如果没有可复用 workspace，运行 `agentic-extract auto` 新建
   workspace，让 Phoenix 自动生成 schema、business_guide、labels 和
   `program.py`。
7. 如果 `xdev run` 发现字段缺失，但原文中存在证据，不要停下来问用户，
   直接运行 `agentic-extract run` 进入自动修复。
8. 修复后运行 `xdev eval` 或 `xdev evaluate` 回归已有标注样本。
9. 从 Phoenix 原生日志中提炼经验并更新 workspace 记忆。
10. 导出抽取结果到 `<workspace>/results.jsonl`：

```bash
for doc_id in $(xdev list --workspace <workspace> 2>/dev/null | grep -oP '^\d+'); do
  echo "{\"doc\": \"$doc_id\", \"result\": $(xdev run $doc_id --workspace <workspace> 2>/dev/null | python3 -c 'import sys,json,re; t=sys.stdin.read(); m=re.search(r"\{.*\}", t, re.DOTALL); print(m.group() if m else "null")')}"
done > <workspace>/results.jsonl
```

11. 生成运行统计到 `<workspace>/run_stats.md`（总耗时、每轮迭代耗时与 token 消耗）：

```bash
python3 <phoenix-skill-root>/phoenix-evolution/scripts/summarize_run_stats.py \
  --workspace <workspace> \
  --output <workspace>/run_stats.md
```

12. 输出最终抽取结果、准确率、修改文件、经验沉淀位置，以及运行耗时和 token 消耗汇总。

## 运行预算

默认使用充分预算。所有由本 skill 发起的 `agentic-extract auto` 和
`agentic-extract run` 命令，都应带上：

```powershell
--budget full
```

除非用户明确要求快速试跑，或当前任务只是 smoke test，否则不要使用默认
`standard` 或 `fast` 预算。`budget full` 会给 Phoenix 更多外层迭代轮数和
单个 agent 修复空间，适合自动修复、经验沉淀和完整回归流程。

## 最小用户输入

用户不需要描述完整流程。下面这些都应该能触发自动流程。

### 只给本地 PDF

```text
用 Phoenix 抽取：
<pdf-path>
```

行为：

1. 自动判断文档类型。
2. 自动搜索可复用 workspace。
3. 如果匹配成功，复用其 schema 并运行 `xdev run`。
4. 如果没有匹配项，使用 `agentic-extract auto` 新建 workspace。
5. 自动继续修复、评估和经验沉淀。

### 本地 PDF + 字段

```text
用 Phoenix 抽取：
<pdf-path>

字段：
公司名称、股东大会届次、股东大会召开时间、股东大会召开地点
```

行为：优先使用用户给出的字段。若存在匹配 workspace，则复用；否则用这些字段
创建新 workspace。

### 本地 PDF + workspace

```text
用 Phoenix 抽取：
<pdf-path>

workspace：
workspace_gudongdahui_1
```

行为：优先使用用户指定的 workspace，运行 `xdev run`，必要时自动修复并回归评估。

### 下载公告后抽取

```text
从巨潮网下载一份年度股东大会通知公告，并用 Phoenix 抽取。
```

行为：先小批量下载公告，选择最合适的 PDF，然后进入同样的复用或新建 workspace
流程。

## Workspace 决策

如果用户指定了 workspace，优先使用它。

如果用户没有指定 workspace：

1. 扫描本地已有 workspace，比较 schema、`business_guide.md`、文档类型和
   `evolution_notes.md`。
2. 对高置信匹配项自动复用。
3. 如果多个 workspace 都像，但 schema 或文档族冲突，只在能明确判断时自动选择。
4. 如果没有匹配项，自动用 `agentic-extract auto` 创建新 workspace。

只有这些情况需要询问用户：

- 文档类型无法可靠识别
- 多个候选 workspace 的 schema 冲突
- 用户指定字段和候选 workspace schema 冲突
- 业务口径需要人工判断
- 模型、API、网络或文件权限阻塞流程

## 目录约定

## 路径解析规则

执行命令前先解析这些根目录：

1. `<project-root>`：Phoenix 项目根目录。优先使用当前工作目录；如果当前目录不是
   Phoenix 项目，则向上查找包含 `pyproject.toml`、`src/`、`docs/skills/` 或
   `local/workspaces/` 的目录。
2. `<phoenix-skill-root>`：当前 skills 根目录，例如包含 `phoenix/`、
   `phoenix-evolution/`、`phoenix-cninfo-pipeline/` 的目录。
3. `<workspace>`：用户给出的 workspace 路径，或自动匹配/新建的 workspace。
4. `<pdf-path>`：用户给出的 PDF 路径，或从巨潮网下载后得到的 PDF 路径。

不要在通用 skill 中写死 `D:\...`、`C:\Users\...` 或某个用户机器上的绝对路径。
只有用户明确给出绝对路径时，才直接使用该路径。

建议把同一次任务保存在一个本地运行目录中：

```text
<project-root>/local/cninfo_announcements/<run-id>/
  metadata.json
  metadata.jsonl
  pdfs/
  workspace/
  logs/
```

如果项目已有自己的目录约定，优先遵守项目现有约定。

## 经验沉淀与日志

每次流程完成或失败后：

1. 如果运行过 `agentic-extract`，使用 `phoenix-evolution` 读取 Phoenix 原生日志：
   `.agent_state/events.jsonl`、`.agent_state/iterations/`、
   `.agent_state/current.json`。
2. 优先使用自动提炼脚本：

```powershell
python <phoenix-skill-root>\phoenix-evolution\scripts\extract_native_log_experience.py `
  --workspace <workspace>
```

3. 从原生日志得到的经验标记为 `native-agentic`。
4. Codex 外部执行的 shell 命令、直接文件修改、诊断失败等，作为 `codex-side`
   记录到 `run_commands.md` 和 `conversation_summary.md`。
5. 无论流程成功还是失败，都必须确保下面三份 workspace 记忆文件存在，并采用
   追加方式写入，不要覆盖旧经验：
   - `.agent_state/evolution_notes.md`
   - `.agent_state/run_commands.md`
   - `.agent_state/conversation_summary.md`
6. `native_log_archive_*.md` 是 Phoenix 原生日志证据归档；上面三份文件是给下次
   运行直接复用的工作记忆。生成原生日志归档后，还要把其中可复用结论压缩写入
   `evolution_notes.md`。

## 最终回复

流程结束时，向用户报告：

- 输入 PDF 或巨潮网下载条件
- 选择或创建的 workspace
- 抽取字段和值
- 是完整复用、部分复用，还是新建 workspace
- 是否发生自动修复
- 如果存在标注集，最终基线评估准确率
- 修改了哪些文件
- 原生日志或经验归档保存在哪里

保持回复简洁，但要足够让用户不用打开所有日志也能判断本次流程是否成功。

## 最小 Smoke Test

下载前可以先用小页数测试巨潮网检索：

```powershell
python <project-root>/docs/skills/cninfo-announcement-fetch/scripts/fetch_cninfo_announcements.py `
  --category annual_report `
  --start-date 2024-01-01 `
  --end-date 2024-12-31 `
  --page-size 2 `
  --max-pages 1 `
  --output-dir <project-root>/local/cninfo_announcements/smoke_annual_2024
```

确认 `metadata.json`、`metadata.jsonl` 和 `pdfs/` 正常后，再进入 Phoenix 抽取流程。
