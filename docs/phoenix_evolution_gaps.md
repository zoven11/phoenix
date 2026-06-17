# Phoenix 自进化缺口分析

本文整理当前 `Phoenix` 分支距离“可自进化、可记忆”的目标还缺什么。

## 现状

当前 Phoenix 分支已经具备：

- PDF / workspace 输入
- 运行 `agentic_extract`
- 评估并保存新的 `ExtractConfig`
- 支持 `phoenix_workspace` 类型配置
- 支持从 PDF 冷启动、继续迭代、重新评估

相关入口：

- [`api/v1/phoenix.py`](../src/auto_extract_platform/api/v1/phoenix.py)
- [`tasks/phoenix_from_pdfs_task.py`](../src/auto_extract_platform/tasks/phoenix_from_pdfs_task.py)
- [`tasks/phoenix_iteration_task.py`](../src/auto_extract_platform/tasks/phoenix_iteration_task.py)
- [`services/phoenix_service.py`](../src/auto_extract_platform/services/phoenix_service.py)

## 主要缺口

### 1. 缺少显式长期记忆层

当前“记忆”主要散落在：

- workspace 文件
- `.xdev` 产物
- `ExtractConfig.config`
- `PhoenixWorkspace.input_meta`

但还没有一个专门存放：

- 错误模式
- 字段级失败经验
- 修复策略
- 不可破坏约束
- 文档类型差异

的长期记忆结构。

### 2. 缺少版本谱系

现在能生成新 config，但缺少：

- parent / child 关系
- 每次修改原因
- diff 摘要
- 候选版 / 发布版区分
- 自动回滚能力

### 3. 缺少严格的评估门禁

虽然有 `evaluate`，但还没有形成强约束：

- test 集不能退化
- 关键字段不能下降
- 新版本必须过门槛才能激活
- 低质量版本只能作为候选

### 4. 缺少失败反馈闭环

当前失败主要记录在 task log / background task 中，但没有系统化回流到下一轮迭代：

- 上次失败原因
- 上次修复动作
- 下一轮要避免的错误

### 5. 缺少线上反馈学习入口

现在还没有完整的反馈 API，把：

- 人工纠错
- 下游错误样本
- 真实线上失败

转成可学习数据并自动进入 Phoenix 迭代。

### 6. 缺少自触发能力

目前 Phoenix 更偏“被调用后执行”，还不够“自己发现该进化”：

- 哪个字段持续退化
- 哪类文档新增了样本
- 哪个 workspace 需要重训
- 哪个 config 应该回滚

## 建议优先补的能力

1. 建一个 `PhoenixMemory` 表，沉淀错误模式和修复经验。
2. 建一个 `ConfigLineage` 表，记录 config 的来源、diff 和评估变化。
3. 做评估门禁，把 `promote` 和 `candidate` 分开。
4. 增加反馈 API，把纠错样本接入训练闭环。
5. 在运行前注入历史记忆，运行后自动总结经验。
6. 增加回滚机制，避免坏版本进入主链路。

## 长期记忆系统设计

### 设计目标

长期记忆的目标不是简单保存历史日志，而是沉淀一批：

- 可检索
- 可验证
- 可复用
- 可淘汰

的经验资产，让下一轮 Phoenix 迭代能真正参考过去的成功与失败。

换句话说，要把“运行痕迹”升级成“组织经验”。

### 为什么现有记忆还不够

当前已有的 `.agent_state/evolution_notes.md`、task log、workspace 产物和 config meta 只能起到“留痕”作用，但还不具备稳定复用能力，主要问题是：

- 太原始：信息散落在日志和文件里，没有结构化抽象
- 不可验证：看不出某条经验是否真的带来效果提升
- 不可筛选：下一轮运行前很难只拿到当前字段、当前版式、当前错误模式最相关的经验
- 不可淘汰：旧经验、偶然经验和失效经验会越积越多

### 记忆分层

建议把长期记忆拆成四层，而不是直接把总结文本写入一个表。

#### 1. Evidence：原始证据层

记录真实运行事实，不做结论：

- 哪个 workspace
- 哪个 config
- 哪次 task
- 哪个 doc_id
- 哪个字段提错
- 错成什么
- 修复后是否改善
- 评估前后分数变化

这一层的职责是为后续 Observation 和 StrategyMemory 提供依据。

#### 2. Observation：现象层

从证据中抽取稳定现象，但暂不输出修复策略，例如：

- `公告编号` 常混入括号年份
- `审计意见` 在跨页表格中容易漏抽第二行
- 某类文档首页目录会干扰正文字段定位

这一层回答“发生了什么”，但还不直接回答“该怎么修”。

#### 3. StrategyMemory：策略经验层

这是最核心的长期可复用经验层，沉淀“在什么条件下，应该怎么做”，例如：

- 遇到跨页表格时，优先按表头锚点拼接行，不要只按单页最近文本匹配
- 对 `公告编号` 先做去括号、去空白、去年份噪声的标准化
- 目录页噪声严重时，先跳过目录页再搜索正文标题

这一层才是运行前要注入 prompt 的主要内容。

#### 4. ConstraintMemory：约束层

保存“不能犯的错”与“不能破坏的规则”，例如：

- `关键字段A` 宁可返回空值，也不要从相邻字段猜测
- `金额字段` 必须标准化为纯数字字符串
- test 集准确率下降时禁止自动 promote

约束类记忆通常比技巧类经验更适合长期保留。

### 建议的数据模型

#### `PhoenixMemory`

建议把长期经验统一存到 `PhoenixMemory` 表，支持 Observation、StrategyMemory、ConstraintMemory 等不同类型。

建议字段：

- `id`
- `workspace_id`
- `config_id`
- `scope`：`global/workspace/category/field`
- `memory_type`：`observation/strategy/constraint/error_pattern`
- `field_name`
- `doc_type`
- `problem_pattern`
- `applicable_conditions`
- `recommended_action`
- `forbidden_action`
- `evidence_refs`
- `quality_score`
- `use_count`
- `success_count`
- `failure_count`
- `status`：`candidate/active/suppressed/retired`
- `last_validated_at`
- `superseded_by`

说明：

- `scope` 用于检索时控制命中范围
- `quality_score` 用于排序和降权
- `status` 用于生命周期管理
- `evidence_refs` 用于追溯这条经验的证据来源

#### `PhoenixMemoryEvidence`

如果希望后续可追溯性更强，建议把原始证据单独存表。

建议字段：

- `id`
- `workspace_id`
- `config_id`
- `task_id`
- `doc_id`
- `field_name`
- `error_type`
- `wrong_value`
- `correct_value`
- `before_score`
- `after_score`
- `event_ref`
- `created_at`

这层相当于长期记忆的事实底座。

### 经验生成流程

长期记忆不应直接由 agent 自己宣布成立，而应走“证据 -> 候选经验 -> 验证 -> 入库”的流程。

#### Step 1：收集证据

每次 `phoenix_from_pdfs_task` 或 `phoenix_iteration_task` 运行结束后，收集：

- overall evaluation
- field-level accuracy 变化
- regression 文档列表
- 新增 bad case
- `program.py` diff 摘要
- 本轮 prompt / repair 指令摘要
- 关键 agent 事件和错误事件

#### Step 2：生成记忆候选

从证据中提炼候选经验 `memory_candidate`：

- 问题模式是什么
- 在什么条件下出现
- 本轮采取了什么修复动作
- 结果是否改善
- 是否存在副作用
- 哪些条件下不适用

这一步可以由 LLM 辅助总结，但输出必须结构化。

#### Step 3：经验验收

候选经验生成后，不直接进入长期记忆，而是要验证：

- 是否有真实 evidence 支撑
- 是否在本轮修复后带来了可观测改进
- 是否只是对单一文档偶然成立
- 是否引入了其他字段或 test 集退化
- 是否描述得足够具体，能指导下次运行

只有通过验收的候选才进入 `PhoenixMemory(status="active")`。

#### Step 4：记忆入库和降权

如果经验成立：

- 新建或更新 `PhoenixMemory`
- 增加 `success_count`
- 更新 `quality_score`
- 刷新 `last_validated_at`

如果经验效果不稳定：

- 保留为 `candidate`
- 或降为 `suppressed`

如果被后续经验取代：

- 标记 `superseded_by`
- 或改为 `retired`

### 运行前如何复用长期记忆

长期记忆不应该整库注入 prompt，而是按上下文做精确检索。

#### 检索维度

建议按以下维度检索：

- 当前 `workspace_id`
- 当前 `category_code`
- 当前 `field_name`
- 当前 `dataset`（train/test/repair/auto）
- 当前错误模式或低分字段
- 最近一次失败的 regression 摘要

#### 排序规则

建议按以下优先级排序：

1. `scope` 匹配度
2. `field_name` / `doc_type` 命中度
3. `quality_score`
4. `success_count`
5. `last_validated_at`

#### 注入规则

建议每次只注入 5 到 12 条最相关经验，不要把全部历史塞进 prompt。

推荐统一格式：

```text
[问题模式]
审计意见字段在跨页表格中常漏抽第二行。

[适用条件]
文档含连续表格，且表头在上一页、值在下一页。

[建议策略]
先按表头定位字段块，再做跨页拼接；不要只按单页最近文本匹配。

[约束]
若无法确认跨页延续关系，返回空值，不要猜测。

[证据]
iter_xxx 中 8 个样本修复 6 个，test field accuracy 0.62 -> 0.88
```

### 记忆生命周期

长期记忆必须能成长，也必须能老化。

建议状态流转如下：

- `candidate`：新生成，尚未充分验证
- `active`：多次验证有效，可用于默认注入
- `suppressed`：存在一定价值，但近期效果不稳定，默认不注入
- `retired`：已过时或被替代，不再使用

建议规则：

- 新经验默认进入 `candidate`
- 连续 2 到 3 次命中后验证有效，转为 `active`
- 连续多次被引用但收益不明显，降权或转 `suppressed`
- 被更新经验替代后转 `retired`
- 长时间未验证或适用条件变化时重新审核

### 什么样的经验值得长期保留

建议只长期保留三类：

- 跨多个文档反复成立的高复用策略
- 能显著防止回归的高价值约束
- 能稳定识别并修复的错误模式

不建议长期保留：

- 只对单个文档偶然成立的修复技巧
- 没有证据支撑的主观判断
- 只有“这次试了一下”但无法复现的经验
- 无法转化为下轮决策输入的泛化总结

判断标准很简单：这条经验在下一轮运行时，是否能具体改变 agent 的决策。

### 与现有 Phoenix 流程的接入点

#### 运行前

在 `compose_prompt_with_experience(...)` 之前增加：

- `retrieve_phoenix_memories(...)`
- `compose_prompt_with_memory(...)`

由长期记忆检索结果构造本轮 prompt 上下文。

#### 运行后

在 `phoenix_from_pdfs_task.py` 和 `phoenix_iteration_task.py` 结束阶段增加：

- `collect_memory_evidence(...)`
- `build_memory_candidates(...)`
- `validate_memory_candidates(...)`
- `upsert_phoenix_memories(...)`

#### Gate 失败时

如果候选版本在评估门禁中失败，应自动生成一条 regression 类候选记忆，重点记录：

- 哪些字段下降
- 哪些修复动作可能导致退化
- 下次迭代应避免什么

### 分阶段落地建议

建议按下面顺序实现长期记忆，而不是一次性做成大而全系统：

1. 先建 `PhoenixMemory` 和 `PhoenixMemoryEvidence`，把经验和证据分开存
2. 在迭代任务结束后自动生成 `candidate memory`
3. 在运行前按 workspace/category/field 检索注入小规模记忆集
4. 增加基于评估结果的自动验收和降权逻辑
5. 再接入线上反馈样本，让人工纠错也能进入记忆体系

## 记忆系统的一句话原则

长期记忆不是“把历史写下来”，而是：

**把真实证据提炼成可检索的策略，再用后续评估不断验证、淘汰和升级。**

## 一句话结论

当前 Phoenix 已经能“生成新版本”，但还不能稳定地“记住经验、判断好坏、避免遗忘、从反馈中自修复”。要到真正的自进化系统，核心是补齐：**长期记忆、版本谱系、评估门禁、反馈闭环、自触发、可回滚发布**。

## 第一阶段落地约束

长期记忆的第一阶段实现遵循两个硬约束：

- 记忆代码单独放在 `src/agentic_extract/evolution_memory/`
- 记忆运行时文件单独放在 workspace 下的 `.phoenix_memory/`，不能混入源码目录，也不能混入 `.agent_state/`

当前第一阶段只做三件事：

- 提供独立的长期记忆模块骨架
- 提供文件型运行时存储（`memories.jsonl`、`usage.jsonl`、`index.json`）
- 在 `runner.py` 的初始 prompt 前注入已验证的长期记忆上下文

当前第二阶段补充：

- 在每轮 iteration 结束后写入 `evidence.jsonl`
- 在整次 run 结束后从 evidence 提炼 `candidates.jsonl`
- 使用保守规则把部分 candidate 晋升到 `memories.jsonl`
- 对同类 memory 做基础去重合并，并记录 `use_count`
- 在 run 结束后根据结果回写 `success_count / failure_count / quality_score / status`

当前第一阶段暂不做：

- 自动生成 memory candidate
- 自动验证经验质量
- 自动写入新长期记忆
- skill 文档自动导出

说明：

- `evidence.jsonl` 是原始运行证据
- `candidates.jsonl` 是候选经验，只是待验收材料
- `memories.jsonl` 才代表已进入长期复用池的经验
- 当前晋升规则仍是最小版，只校验是否有问题模式、建议动作和证据引用
- 当前已支持最基础的重复 memory 合并，但还没有更细的质量衰减和淘汰规则
- 当前已支持最基础的 run 反馈回写：成功提升质量分，连续失败可降为 `suppressed`

也就是说，第一阶段先打通“独立目录 + 独立模块 + 运行前读取”的链路，后续再继续补“运行后沉淀”和“经验升级”。
