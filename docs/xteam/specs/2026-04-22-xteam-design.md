# xTeam Design Spec · 需求开发(PRD → 技术方案 + 任务拆解)

- 版本: v1 (首版)
- 日期: 2026-04-22
- 作者: Sean + xteam brainstorming session
- 状态: Draft,待 review

---

## 0. 摘要

xTeam 是一个运行在 Claude Code 插件(本仓库,基于 superpowers fork,完全脱钩上游)中的多 agent 协同系统。总目标是深度使用 AI 提升互联网业务的功能开发迭代与运营全流程。首版聚焦「需求开发」场景中的一段:**输入结构化 PRD,输出技术方案 + 任务拆解,到可开工为止**。

### 一句话定义

> xTeam v1 = 一个 Claude Code 插件,读入结构化 PRD,通过 MCP 拉团队知识库,由 6 个 agent(主持/架构/数据/性能/安全/QA,其中主持人 = 主对话 Claude,架构师 = 1 个 draft/merge 双模 subagent,data/perf/security/qa = 4 个 reviewer subagent)组成圆桌,固定 2 轮评审 + 中间插点问人 + 最终人兵兜底收敛,产出「技术方案 Markdown + writing-plans 兼容的任务拆解」,并把圆桌中产生的新决策在人审后写回 KB。

### 核心价值(按优先级)

1. **一致性 — 把资深经验规模化**(第一位)
2. 速度 — 编写时间从天压到小时(附带价值)
3. 质量 — 多视角覆盖减少漏考(附带价值)

"一致性"是设计基调:重点不是 LLM 自由发挥,而是把资深架构师经验编码成可复用、可审计、有质量基线的 agent 协同流程。多 agent 的本质是「不同视角的 checklist + 启发式,强制覆盖每个专业维度」。

### 边界(不做清单)

1. 不做需求收集 — PRD 必须已就绪
2. 不做代码生成 — 产物到 plan.md 停,交给 `subagent-driven-development`
3. 不做多人实时协作 — 单用户驱动
4. 不做 KB 编辑 UI — 复杂编辑去 KB
5. 不做 IM/Jira 集成 — 外部事
6. 不做跨 session 方案演进比较 — KB 是唯一长期记忆
7. 不做 agent 自主创造新角色 — 6 个角色写死

---

## 1. 系统架构

### 1.1 整体流程图

```
┌──────────────────────────────────────────────────────────────┐
│  Claude Code 会话 (xTeam 插件 = 主持人 Claude 本人)           │
│                                                              │
│   /xteam-design <prd-path>                                   │
│          │                                                   │
│          ▼                                                   │
│   Phase 0  Intake       ─ 读 PRD、校验结构化模板             │
│          │              ─ 不合规则提示 PM 补全                │
│          ▼                                                   │
│   Phase 1  Context      ─ 调 MCP KB:按 PRD 涉及模块预抓       │
│          │              ─ 缺口清单一次性问 PM 补齐             │
│          ▼                                                   │
│   Phase 2  Draft        ─ 派 architect subagent 出"方案 v0"   │
│          │                                                   │
│          ▼                                                   │
│   Phase 3  Round 1 ────▶ 并行派 4 个 reviewer subagent        │
│          │              (data / perf / security / qa)        │
│          │              ─ architect(mode=merge) 合成 v1       │
│          ▼                                                   │
│   Phase 3.5 Mid-check   ─ 四个不确定信号任一超限 → 一次性问人 │
│          │              ─ 人回答 → KB 临时层(全员可见)       │
│          ▼                                                   │
│   Phase 4  Round 2      ─ 同 Round 1 结构,基于 v1 复评       │
│          │              ─ architect(mode=merge) → v2          │
│          ▼                                                   │
│   Phase 5  Converge     ─ 未决分歧/未回答必答项 → 人兜底      │
│          │              ─ 人回复后 architect 终稿 v_final     │
│          ▼                                                   │
│   Phase 6  Output       ─ 写 tech-design.md                   │
│          │              ─ 写 plan.md (writing-plans 兼容)     │
│          │              ─ 生成 kb-diff.md (人审)              │
│          ▼                                                   │
│   Phase 7  KB writeback ─ 人 approve 后经 MCP 写回 KB         │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

### 1.2 三个角色层级

1. **主持人 (Orchestrator)** = 主对话里的 Claude 自己,**不是 subagent**。持有会话上下文、用户交互权、MCP 工具。负责所有 Phase 的调度、合并调用、人机交互。
2. **Subagent 角色** = 5 个 prompt 模板(architect 的 draft/merge 双模共用一份 prompt,+ 4 个领域专家:data / perf / security / qa)。每次派发时新实例化,**无状态、独立上下文**。拿到的所有输入由主持人拼装。
3. **Skill 层** = `xteam-design`(主 skill)+ `xteam-convene-roundtable`(圆桌算法)+ `xteam-kb-writeback`(人审落盘)。

#### 1.2.1 Role × Mode 正交(面向未来阶段)

xTeam v1 只覆盖「需求开发」(PRD → 技术方案 + 拆解),所有领域 agent 在 v1 都工作在 **review 模式**(出意见,不原创、不执行)。但未来扩展到研发 / 测试 / 运营阶段时,同一个 role(例如 data)可能需要新的 mode(例如产出 migration 脚本)。

为此:

- **Agent 文件命名中性化**:`agents/xteam-agent-<role>.md`,而不是 `xteam-reviewer-<role>.md`。文件名只承诺「这是一个 xTeam agent」,不锁定它的工作模式。
- **Mode 在 agent prompt 内部切换**,架构师已是活样本:同一个 `xteam-agent-architect.md` 通过 `mode: draft | merge` 切行为。未来领域专家扩 mode 时按此套路。
- **I/O schema 跟随 mode**:v1 只有一份 `reviewer-output.schema.json`,未来新增 mode 时各自加自己的 schema,不改现有的。
- **v1 描述性语境中仍使用「reviewer」一词**,代指「工作在 review 模式的 agent」。文件标识和工作模式分开——这是讨论时不致混淆的关键。

这个设计让 v1 的落地不增加任何复杂度(prompt / schema / 测试结构都不因为命名而改变),同时给后续阶段留好接口。

### 1.3 关键不变式

- 每轮所有 reviewer 拿到**同一份 draft + 同一份 KB 片段**,不互相看彼此意见 → 视角独立,无 persona 泄漏
- 合并永远由 `architect` subagent(mode=merge)做,不在主持人里用自由文本合并 → 合并逻辑可审计、可回归测试
- 所有 subagent 返回**结构化 JSON**,不返回自由文本 → 主持人无需「读懂」自然语言
- 所有 MCP 调用走主持人,不走 subagent → 一次 KB 快照 + 所有 subagent 看同一份事实
- 人兜底只在 P1 / P3.5 / P5 三个预定点,reviewer 本身永远不直接问用户

---

## 2. Agent 契约 (I/O Schema)

### 2.1 共享输入

主持人每次派发 subagent 时拼装下列输入:

```json
{
  "prd": { /* 结构化 PRD 全文 */ },
  "kb_context": {
    "tech_stack": "...",
    "services": [...],
    "data_stores": [...],
    "conventions": "...",
    "historical_pitfalls": [...],
    "relevant_adrs": [...]
  },
  "current_draft": "<tech-design.md 当前版本; Phase 2 为空>",
  "round": 1,
  "open_questions": [...],
  "must_answer_items": [
    { "id": "schema", "applicable": true, "status": "missing" },
    { "id": "api_contract", "applicable": true, "status": "draft" },
    ...
  ]
}
```

### 2.2 必答项清单 (11 项)

主持人在 Phase 1 结束时判定每项 `applicable`,Round 1/2 只追踪 `applicable = true` 的项。Round 2 结束时所有 `applicable = true` 必须是 `draft` 或 `n/a`,否则强制走 P5 人兜底。

| id | 触发条件 | 适用角色 |
|---|---|---|
| `schema` | 所有场景 | architect / data |
| `api_contract` | 所有场景 | architect |
| `failure_modes` | 所有场景 | architect / qa |
| `migration` | 所有场景 | architect / data |
| `observability` | 所有场景 | architect / perf |
| `rate_limit` | 所有场景 | architect / perf |
| `rollback` | 所有场景 | architect / qa |
| `compat_and_isolation` | 仅当 PRD 涉及存量模块主要功能特性时 | architect / data / qa |
| `content_safety` | 内容/社交专属 | architect / security |
| `cache_strategy` | 内容/社交专属 | architect / perf / data |
| `hotspot` | 内容/社交专属 | architect / perf |

#### 2.2.1 `compat_and_isolation` 详细要求

**要求方案里回答 4 项**:

1. **影响面** — 受影响的客户端版本范围 / 调用方 / 数据范围(一两句话即可)
2. **兼容策略**(三选一 + 理由):
   - 向后兼容(老调用方无感)
   - 新老并存(按灰度 / 版本切流)
   - 仅对新版本开放(能力协商 / feature flag)
3. **隔离手段**(用到哪项说哪项,不强填):
   - 数据:是否同表 / 迁移路径
   - 流量:灰度维度
   - 故障:新功能故障对老功能的影响边界
4. **接口破坏性变更** — 有 / 无。若有,说明切换节奏(无需正式废弃计划)

**隐含约定**:老版本一经发出视为永久共存,下线老路径是独立需求,不在本方案范围。该约定写进 architect agent prompt,防止乱提「老接口下线时间」。

### 2.3 专家 reviewer 输出契约(统一 schema)

所有 4 个 reviewer(data / perf / security / qa)返回同一结构:

```json
{
  "role": "data",
  "round": 1,
  "verdict": "changes_requested",   // approved | changes_requested | block
  "issues": [
    {
      "severity": "critical | major | minor",
      "location": "§3.2 数据模型",
      "problem": "评论表 user_id 未建索引,按用户拉取评论会全表扫",
      "suggested_fix": "加 idx_comment_user_id_created,查询走 covering index",
      "rationale": "KB.historical_pitfalls#P-2024-07 明确过此类问题曾致慢查询"
    }
  ],
  "must_answer_updates": [
    { "id": "schema", "status": "draft" }
  ],
  "open_questions_for_human": [
    "冷热分离阈值 30 天 vs 90 天?KB 无先例,需业务决策"
  ]
}
```

**统一 schema 的意义**:合并 agent 只需一套逻辑(按 location 聚合、按 severity 排序、并 must_answer_updates、汇 open_questions_for_human),没有特判。

### 2.4 architect agent 的两种模式

同一个 prompt,通过 `mode` 参数切换行为:

- **`mode: "draft"`** (Phase 2): 输入 PRD + KB,输出初版 `tech-design.md` + 初始 `must_answer_updates`
- **`mode: "merge"`** (Phase 3/4/5): 输入 `current_draft` + 本轮所有 reviewer JSON,输出新版 `tech-design.md` + must_answer 状态更新 + 保留的 open_questions

**合并规则(写死在 prompt)**:

1. `critical` issue **必须**修进方案;修不了 → 移到 `open_questions_for_human`
2. `major` issue 同上,但允许在方案里标注「已接受风险 + 原因」而不修
3. `minor` issue 可选吸收,决定必须列入 changelog
4. 冲突意见(两个 reviewer 建议相反):architect 必须显式裁定并写明理由,**不允许模糊表述**

### 2.5 plan-composer agent

**纯格式转换器**,不参与圆桌意见逻辑。输入 v_final `tech-design.md`,输出 `superpowers:writing-plans` 兼容的 `plan.md`。

独立存在的理由:避免「写方案心智」和「分解任务心智」混淆。格式转换错了,不该影响方案本身。

---

## 3. 数据流与主持人状态机

### 3.1 Phase 状态机

```
START → P0 Intake → P1 Context → P2 Draft → P3 Round 1 →
P3.5 Mid-check → P4 Round 2 → P5 Converge → P6 Output →
P7 KB Writeback → DONE
```

### 3.2 每阶段的 I/O 与失败约束

| 阶段 | 输入 | 输出 | 失败处置 |
|---|---|---|---|
| P0 Intake | PRD 路径 | 合法 PRD(结构化) | 不合规直接退出,列缺失字段 |
| P1 Context | PRD | KB 会话快照 + 缺口清单已解决 | MCP 不可达退出(见 §4.5) |
| P2 Draft | PRD + KB | tech-design v0 + must_answer 初始状态 | architect 失败:重试 1 次再退出 |
| P3 Round 1 | v0 + KB + must_answer | 4 份 reviewer JSON → merge → v1 | 单 reviewer 失败:标缺席,继续 |
| P3.5 Mid-check | v1 + Round 1 输出 | 若触发:人回复进 KB 临时层 | 用户中断:snapshot 保留,等 resume |
| P4 Round 2 | v1 + KB(含临时层) | 4 份 reviewer JSON → merge → v2 | 同 P3 |
| P5 Converge | v2 + 未决项 | v_final(人回答 → architect merge) | 人问题 > 20:判 PRD 不成熟,退出 |
| P6 Output | v_final | tech-design.md + plan.md + kb-diff.md | 写失败:重试并让用户确认路径 |
| P7 Writeback | kb-diff.md | KB 更新结果 | 写失败:保留本地,提示手工重试 |

### 3.3 P3.5 Mid-check 阈值

**任一超限即触发**,主持人中断圆桌,一次性批量问人。人回复进 KB 临时层(session-scoped),Round 2 所有 agent 可见。

| 信号 | 阈值 |
|---|---|
| 本轮所有 reviewer 的 `open_questions_for_human` 累计 | ≥ 5 条 |
| 本轮 `critical` issue 未被 architect 修/裁定 | ≥ 1 条 |
| `applicable=true` 的必答项在 v1 里仍 `missing` | ≥ 3 项 |
| architect merge 时显式标「无法裁定」的冲突 | ≥ 2 条 |

阈值第一版硬编码在 `skills/xteam-design/midcheck-thresholds.md`,上线后 4 周抽到 `.xteam/config.yml`。

### 3.4 人兜底的三个预定点

- **P1 缺口清单**:MCP 拉回后仍缺、或必答项 applicability 不确定的问题
- **P3.5 Mid-check**:由阈值触发,中途问一次
- **P5 Converge**:Round 2 结束的最后一次兜底

**reviewer 永远不直接问用户**,只能写到 `open_questions_for_human`,由主持人汇总后在上述三点之一释放给用户。

### 3.5 状态持久化

原型期只保留一份 snapshot:
- 每个可能退出的点(MCP 不可达、用户中断、agent 连续失败)**先写 snapshot 再退出**
- 路径: `.xteam/<session-id>/snapshot.json`
- 结构见 §5.2
- 恢复: `/xteam-resume <session-id>` 重入对应 Phase

**不做**增量日志、版本演进、多分支探索——违反 YAGNI,且真实一次圆桌 15–30 分钟,可接受重跑。

---

## 4. KB 交互

### 4.1 三层读路径

```
永久 KB (MCP)
    │ P1 预抓 一次性快照
    ▼
会话 KB 快照 (主持人内存)
    │ + P3.5 人补充 (若触发)
    ▼
临时 KB 层 (session-only,不写永久 KB)
    │ 分发给 subagent 时按角色切片
    ▼
角色 KB 片段 (每个 reviewer 只拿自己相关那部分)
```

关键不变式:**人在 P3.5 补的内容不污染永久 KB**——只有 P7 经人审通过的 diff 才写永久 KB。

### 4.2 P1 预抓策略

主持人用 PRD 的「涉及模块」字段调 MCP,每个模块拉回:

```
{
  module_profile,        // 技术栈、依赖、核心数据表、负责人
  recent_incidents,      // 最近 N 个月事故
  relevant_adrs,         // 相关架构决策记录
  historical_pitfalls,   // 已知的坑
  conventions            // 模块特殊约定
}
```

**若 PRD 某个「涉及模块」KB 无记录**:加入 P1 缺口清单,让 PM 选:
- (a) 填一个简短 profile 临时用
- (b) 按新模块处理
- (c) 改 PRD 中的模块名

### 4.3 角色切片规则(硬编码表)

| 角色 | 拿到的 KB 字段 |
|---|---|
| architect | **全部**(要写方案,需要最大视野) |
| data | `module_profile.data_stores` + `conventions.data` + `historical_pitfalls#schema\|migration` + `relevant_adrs#data` |
| perf | `module_profile.capacity` + `recent_incidents#performance` + `historical_pitfalls#hotspot\|cache` |
| security | `conventions.security` + `historical_pitfalls#auth\|data_leak` + `relevant_adrs#security` |
| qa | `module_profile.test_strategy` + `conventions.testing` + `recent_incidents#regression` |

切片规则实现在 `skills/xteam-design/kb-slicing-rules.md`。增删 KB 字段必改此文件。

### 4.4 P7 写路径

只在**圆桌完整跑完、产物已落盘**后触发。

**kb-diff.md 结构**:

```yaml
candidate_updates:
  - type: new_adr
    scope: module/comment
    summary: "评论冷热分离阈值设为 30 天"
    rationale: "本次圆桌 data agent 与 PM 共识"
    source: "P3.5 人补充 + P4 architect 裁定"
  - type: new_pitfall
    scope: module/feed
    summary: "..."
  - type: update_convention
    path: conventions.cache.default_ttl
    before: "300s"
    after: "600s"
    rationale: "..."
```

**三类 diff(v1 仅支持这三类)**:
- `new_adr` — 新架构决策
- `new_pitfall` — 新发现的坑
- `update_convention` — 约定值更新

其它类型(如 update_module_profile)v1 不支持,人直接去 KB 维护。

**人审体验**:
- 终端逐条列出 diff,每条默认勾选
- 回车:全部 approve;空格切换;可选 reject / edit / skip
- 写入时附 `source: "xteam-session/<id>"` 元数据便于追溯

### 4.5 MCP 不可达 = 硬停

**KB 必须可达,不提供任何降级路径。**

- **P1 预抓失败**:重试 2 次指数退避 → 仍失败 → 写 snapshot → 退出 `EXIT_KB_UNREACHABLE`。提示「请修复 MCP 后 `/xteam-resume <session-id>`」。
- **P1 预抓成功但返回空**(KB 可达但模块无记录):不算失败,走 §4.2 缺口清单
- **P7 写入失败**:保留本地 `kb-diff.md`,提示「稍后 `/xteam-writeback <session-id>` 重试」(不影响方案和 plan 已落盘)

**没有 `--no-kb` 开关**。命令行不存在此选项。KB 是燃料,缺燃料别跑。

---

## 5. 失败模式与系统边界

### 5.1 失败处置总表

| 失败点 | 第一反应 | 重试 | 最终失败行为 |
|---|---|---|---|
| PRD 不合规 | 退出 P0 | 不重试 | 返回详细缺字段清单 |
| MCP 不可达 | 重试 2 次指数退避 | 2 | snapshot + `EXIT_KB_UNREACHABLE` |
| MCP 返回空 | 不是失败 | — | 进 P1 缺口清单 |
| Subagent 非法 JSON | 重试(附格式错误提示) | 1 | P2/Merge:退出;P3/4 Review:标缺席 |
| Subagent 超时 | 重试 | 1 | 同上 |
| Round 1 某 reviewer 缺席 | 继续 | — | Round 2 merge prompt 明示「上轮 X 缺席,请补查该维度」 |
| Round 2 某 reviewer 缺席 | 继续进 P5 | — | P5 人兜底清单附「X 本次未评审,请人工补查」 |
| Architect(draft/merge) 失败 | 重试 | 1 | 无 architect = 无方案,退出保 snapshot |
| P3.5 用户跑路 | snapshot | — | 等 `/xteam-resume` |
| P5 人问题 > 20 | 判 PRD 不成熟 | — | 退出建议回 brainstorming |
| P6 文件写失败 | 重试并问路径 | 1 | 打印内容到终端,让用户另存 |
| P7 KB 写失败 | 保留 kb-diff.md | — | 提示 `/xteam-writeback` 重试 |

**贯穿原则**:
1. **snapshot 永远先写**——任何可能退出的点先 snapshot 再退出
2. **重试次数全系统一致**:网络类 2 次、格式类 1 次

### 5.2 Snapshot 结构

`.xteam/<session-id>/snapshot.json`:

```json
{
  "session_id": "...",
  "created_at": "...",
  "phase": "P3.5 | P5 | ...",
  "prd_path": "...",
  "kb_snapshot": { /* §4.2 结构 */ },
  "drafts": { "v0": "...", "v1": "...", "v2": "..." },
  "rounds": {
    "round_1": { "reviewer_outputs": [...], "merge_changelog": [...] },
    "round_2": { ... }
  },
  "must_answer_state": [...],
  "open_questions_for_human": [...],
  "human_responses": [ /* P3.5 / P5 已回答 */ ],
  "last_error": "..."
}
```

一份 JSON 够 resume。不做增量、不做多版本。

### 5.3 P0 拒绝检查

主持人在 P0 除结构化校验外,做 3 个拒绝:

1. **PRD 实际上是 idea** → 拒绝,建议先用 `brainstorming` 把 idea 变 PRD
2. **PRD 其实是技术方案** → 拒绝,xTeam 产出技术方案,不审技术方案
3. **PRD 体量超阈值**(字数 > 5000 或 涉及模块 > 8 个) → 警告但可 `--force`,警告会随产物一起记录「方案覆盖不充分风险」

### 5.4 不做清单(强约束)

写入 `skills/xteam-design/SKILL.md` 与 README,防止范围扩张:

1. 不做需求收集
2. 不做代码生成
3. 不做多人实时协作
4. 不做 KB 编辑 UI
5. 不做 Jira / DingTalk / IM 集成
6. 不做方案评审历史对比
7. 不做 agent 自主创造新角色

---

## 6. 测试与验收

### 6.1 三层测试金字塔

```
    ┌─────────────────────┐
    │  端到端回归(黄金集) │   5-10 个真实 PRD,每周跑一次
    ├─────────────────────┤
    │    圆桌组件测试      │   单 agent I/O 契约 + 合并规则
    ├─────────────────────┤
    │   主持人单元测试     │   状态机转移 + 阈值触发 + 切片规则
    └─────────────────────┘
```

### 6.2 单元层(不跑 LLM)

用 fixture 驱动主持人,验证:

1. 状态机在各输入下走的路径符合 §3.1
2. 必答项 applicability 判定正确(含 `compat_and_isolation` 的触发)
3. P3.5 四个阈值各自/组合超限的行为
4. KB 角色切片与 §4.3 表一致
5. 合并规则(critical 未处理 → 强制进 open_questions)
6. snapshot 在 §5.1 每个失败点都被正确写出

标准 TDD:先红再绿。

### 6.3 组件层(低频跑真实 LLM)

每个 subagent 是「prompt + schema」。验证:

1. **Schema 合法性**:10 个历史输出全部通过 JSON schema
2. **Prompt 稳定性**:同输入 3 次,`issues[]` 数量变动 ≤ 30%,`verdict` 不在 approved ↔ block 之间跳
3. **必答项覆盖度**:给带明显漏洞的 draft(例如缺 schema 章节),对应 reviewer 必须输出指向 schema 的 `must_answer_updates` 或 `issues`

PR 级别跑,不是每次改都跑。

### 6.4 端到端黄金 PRD 集

维护 5–10 个真实 PRD,覆盖:
- 纯新功能(无存量)
- 涉及核心存量模块(激活 compat_and_isolation)
- 高流量内容类(激活 cache/hotspot)
- 带明显漏洞(验证 P0 拒绝)
- 超阈值(验证 P5 劝返)
- KB 完全命中 vs 半命中

每份 PRD 配**语义级断言 YAML**(不对比 LLM 文本):

```yaml
prd: tests/xteam/golden/social-comment-feature.md
must_assert:
  - architect_draft_contains_section: "数据模型"
  - must_answer_compat_and_isolation_is_applicable: true
  - round_1_raises_issue_about: "评论 user_id 索引"
  - final_plan_md_is_writing_plans_compatible: true
  - kb_diff_contains_new_adr: true
forbid:
  - output_mentions: "本方案建议下线老接口"
```

### 6.5 Go/No-Go 清单(上线前)

- [ ] §6.2 全部单元测试通过
- [ ] §6.3 agent schema 合法率 100% / verdict 稳定性通过
- [ ] §6.4 黄金集 ≥ 80% 语义断言通过
- [ ] 完成 ≥ 10 次真实 PRD 圆桌(≥ 3 个业务线),每次采集下述度量信号
- [ ] 度量系统可自动/半自动入库,面板可见
- [ ] 最后 5 次 session 三组指标稳定或改善
- [ ] snapshot/resume 被真实中断场景验证过
- [ ] kb-diff 写回 ≥ 2 个真人走过,无误写事故
- [ ] 上线后 4 周内基于真实数据确立 P50/P75 基线(不阻塞首发)

**核心判据:可见 + 趋势不恶化**,不预设硬阈值。

### 6.6 度量信号(强制采集)

三组信号,每次 session 自动或通过 `/xteam-record-final` 手工登记入库:

#### ① 人工介入次数

| 介入点 | 计数方式 |
|---|---|
| P0 因 PRD 不合规退回 | +1(流程未到 P6,不算出产物) |
| P1 缺口清单问 PM | 清单条数 |
| P3.5 中间插点 | 清单条数 |
| P5 人兜底 | 清单条数 |
| P7 kb-diff 人审非默认 approve | 操作次数 |

#### ② 修改差异幅度(P6 → 最终提交)

- **行级 diff 比例**: `(added + modified + deleted) / total_final_lines`
- **结构级保留率**: xTeam 生成的章节里被完全删掉的比例

实现:P6 落盘给文件打 SHA + 时间戳;`/xteam-record-final <session-id> <final-path>` 让人在提交实施时登记最终版路径,自动计算 diff。未登记的 session 面板标红。

#### ③ 采纳率

- 分子:行级 diff ≤ 20% 的 session 数(后续基线生效后按基线调)
- 分母:进入 P6 的 session 数

### 6.7 运行期度量面板

```
session_id | date | prd_scale | total_interventions
| edit_distance | structure_retention | adopted?
| fallthrough_phase | kb_writeback_count
```

**告警规则**(触发即回头调 prompt,暂停新使用):
- 连续 3 次 `total_interventions > 15`(基线建立后改为相对基线)
- 连续 3 次 `edit_distance > 40%`(基线建立后改为相对基线)
- 周采纳率跌破 50%

**反向验证**:用率下降本身是信号,不能只看绝对值。数据回升时主动问用户「是不是你发现 xTeam 有问题所以少用了」。

---

## 7. 插件结构与文件布局

### 7.1 策略总则

- **fork 完全脱钩上游**(`obra/superpowers`),不打算推回
- **所有 xTeam 新增文件用 `xteam-` 前缀或 `xteam/` 子目录**,与原有内容泾渭分明
- **原有 `skills/`、`agents/`、`commands/` 第一版不改**,需复用就 reference,不复制不修改

### 7.2 目录结构

```
xteam fork 仓库/
├── .claude-plugin/plugin.json                 # 改 name 标识 fork(例:superpowers-xteam)
├── README.md                                  # 可按团队需要重写
├── commands/
│   ├── xteam-design.md                        # 新增 /xteam-design
│   ├── xteam-resume.md                        # 新增
│   ├── xteam-writeback.md                     # 新增
│   └── {原有命令不动}
├── skills/
│   ├── xteam-design/                          # 主持人(§3 状态机)
│   │   ├── SKILL.md
│   │   ├── must-answer-items.md               # §2.2
│   │   ├── kb-slicing-rules.md                # §4.3
│   │   ├── midcheck-thresholds.md             # §3.3
│   │   └── failure-handling.md                # §5.1
│   ├── xteam-convene-roundtable/              # 圆桌算法(Phase 2-5)
│   │   └── SKILL.md
│   ├── xteam-kb-writeback/                    # P7 人审写回
│   │   └── SKILL.md
│   └── {原有 skill 不动}
├── agents/
│   ├── xteam-agent-architect.md             # draft / merge 双模式
│   ├── xteam-agent-data.md                   # v1 仅 review 模式
│   ├── xteam-agent-perf.md                   # v1 仅 review 模式
│   ├── xteam-agent-security.md               # v1 仅 review 模式
│   ├── xteam-agent-qa.md                     # v1 仅 review 模式
│   ├── xteam-agent-plan-composer.md          # 纯工具(非圆桌)
│   └── {原有 agent 不动}
├── schemas/xteam/                             # §2 JSON Schema
│   ├── reviewer-output.schema.json
│   ├── architect-merge-output.schema.json
│   ├── must-answer-state.schema.json
│   ├── snapshot.schema.json                   # §5.2
│   └── kb-diff.schema.json                    # §4.4
├── templates/xteam/
│   ├── prd-template.md                        # §3 P0 硬约束
│   ├── tech-design.md                         # P6 产物骨架
│   └── plan.md                                # writing-plans 兼容骨架
├── tests/xteam/
│   ├── unit/                                  # §6.2 不跑 LLM
│   ├── fixtures/                              # 预录 MCP / reviewer 返回
│   ├── components/                            # §6.3
│   └── golden/                                # §6.4
├── docs/xteam/
│   ├── architecture.md                        # §1 扩写
│   ├── contracts.md                           # §2 扩写
│   ├── state-machine.md                       # §3 扩写
│   ├── kb-interaction.md                      # §4 扩写
│   ├── failure-modes.md                       # §5 扩写
│   ├── testing.md                             # §6 扩写
│   ├── metrics.md                             # §6.6/6.7 扩写
│   └── specs/
│       └── 2026-04-22-xteam-design.md         # 本文件
└── scripts/xteam-record-final.sh              # §6.6 ②
```

### 7.3 依赖关系

```
commands/xteam-design.md
    └─→ skills/xteam-design/SKILL.md
            ├─→ must-answer-items.md
            ├─→ kb-slicing-rules.md
            ├─→ midcheck-thresholds.md
            ├─→ failure-handling.md
            └─→ skills/xteam-convene-roundtable/SKILL.md
                    ├─→ agents/xteam-agent-architect.md
                    ├─→ agents/xteam-agent-{data,perf,security,qa}.md
                    └─→ schemas/xteam/*.json

commands/xteam-writeback.md
    └─→ skills/xteam-kb-writeback/SKILL.md
            └─→ schemas/xteam/kb-diff.schema.json

commands/xteam-resume.md
    └─→ 读 .xteam/<session-id>/snapshot.json
    └─→ 重入 skills/xteam-design/SKILL.md 对应 Phase
```

**不变式**:`agents/xteam-*.md` 不能反过来 import skill 文件。Agent 是无状态叶子,所有协调在主持人一侧。

### 7.4 与现有 superpowers skills 的交接点

- **上游**:用户可选 `brainstorming` 产 PRD 草稿 → 按模板补全 → 喂 `/xteam-design`
- **下游**:`plan.md` 产出后,直接交给 `subagent-driven-development` 或 `executing-plans`

xTeam 不改任何原有 skill 文件,只消费 `plan.md` 的约定。

### 7.5 MCP 接入期望

插件不实现 KB MCP(用户自有)。在 `docs/xteam/kb-interaction.md` 声明期望的工具签名:

```
kb_fetch_module_profile(module_name: string) → ModuleProfile
kb_fetch_recent_incidents(module_name, months) → Incident[]
kb_fetch_relevant_adrs(module_name) → ADR[]
kb_fetch_pitfalls(module_name, categories?) → Pitfall[]
kb_write_adr(adr: ADR, source: string) → writeResult
kb_write_pitfall(pitfall: Pitfall, source: string) → writeResult
kb_update_convention(path, new_value, source) → writeResult
```

若用户 KB 实际签名不同,提供 `kb-adapter.md` 手工配 mapping。v1 不做自动发现。

---

## 8. 实施计划接口(给下游 writing-plans)

本 spec 完成后,移交 `writing-plans` 基于下列要素拆分任务:

**首版实施应覆盖**:
- `skills/xteam-design/` 主持人流程 + 所有子规则文件
- `agents/xteam-agent-*.md` 6 个 agent prompt 文件(architect / data / perf / security / qa / plan-composer;前五个是圆桌参与者,plan-composer 不参与圆桌,仅负责 P6 格式转换)。命名遵循 §1.2.1 role × mode 正交原则,v1 中领域专家 agent 均工作在 review 模式。
- `schemas/xteam/*.json` 5 份 schema
- `templates/xteam/` 3 份模板(尤其 PRD 模板,影响 P0)
- `tests/xteam/unit/` 6 类主持人单元测试
- `tests/xteam/fixtures/` 至少 3 套预录数据
- `tests/xteam/golden/` 至少 5 份黄金 PRD + 断言
- `commands/xteam-{design,resume,writeback}.md`
- `scripts/xteam-record-final.sh`
- `docs/xteam/` 7 份文档(由本 spec 拆解扩写)

**推荐实施顺序**:
1. schemas + templates(基础契约)
2. agents prompts(含 architect 双模式)
3. skills(主持人状态机)
4. commands(入口)
5. 单元测试(TDD)
6. fixtures + golden(集成回归)
7. scripts(度量闭环)
8. docs 扩写(最后,避免改动时文档滞后)

---

## 9. 未决事项(交付后 4 周内解决)

1. **P3.5 阈值从硬编码抽到配置**:等首批真实数据,按 p75 定新阈值
2. **度量基线确立**:介入数、edit distance、采纳率各自的 P50/P75
3. **告警阈值相对化**:从绝对值改为「相对基线的偏移」
4. **内容/社交三个专属必答项的阈值触发条件精化**:首版仅按业务类型粗粒度激活,需观察误杀率
5. **KB 角色切片表的微调**:首批使用后基于 reviewer 投诉「缺关键上下文」或「上下文太多」调整

## 9a. 面向未来阶段的扩展路径(非阻塞)

v1 只覆盖「需求开发」。下列扩展点明确列出以便后续阶段设计:

1. **研发阶段 agent**:在 `xteam-agent-<role>.md` 里新增 `mode: "execute"` 或新建 `mode: "code"` 段。可能需要的新角色文件:`xteam-agent-coder.md`、`xteam-agent-refactorer.md`。
2. **测试阶段 agent**:`xteam-agent-qa.md` 增加 `mode: "design_cases"` 与 `mode: "triage_bugs"`;或新建 `xteam-agent-test-designer.md`。
3. **运营阶段 agent**:新建 `xteam-agent-monitor.md` / `xteam-agent-incident-responder.md` / `xteam-agent-growth-analyst.md`,各自独立 role,工作 mode 由具体场景定。
4. **Skills 扩展**:预计会新增 `xteam-execute-plan`、`xteam-triage-incident` 等 skill,每个 skill 复用主持人编排骨架(Phase 状态机 + snapshot + 度量闭环)。
5. **Schema 扩展**:每个新 mode 新增对应的输出 schema(如 `coder-output.schema.json`),不改现有 `reviewer-output.schema.json`。
6. **KB 交互扩展**:research/ops 阶段对 KB 的读写模式不同(如写 incident 记录、读历史变更),届时扩 §4 的 MCP 工具签名清单,不破坏现有契约。

**原则**:每增加一个阶段 = 一个独立的 scope / spec / plan / 实施周期。不在 v1 里为任何未来阶段铺代码或预埋框架——v1 只确保**命名和契约结构不阻塞未来**即可。

---

## 附录 A. 术语表

| 术语 | 定义 |
|---|---|
| 主持人 (Orchestrator) | 主对话里的 Claude 自己,非 subagent |
| 圆桌 (Roundtable) | 主持人 + architect + 4 个领域专家 agent(v1 均工作于 review 模式)的协作过程(Phase 2-5) |
| Role | Agent 的职能维度(architect / data / perf / security / qa ...)。与 mode 正交。文件命名按 role 区分。 |
| Mode | Agent 的工作模式(v1:draft / merge / review;未来:execute / code / design_cases ...)。在 agent prompt 内部切换,不改文件名。 |
| Reviewer | 指**工作在 review 模式的 agent**。v1 中 4 个领域专家都是 reviewer,但不把这个身份写进文件名。 |
| 必答项 (must_answer_items) | 方案必须覆盖的维度清单,11 项 |
| 会话快照 (session kb snapshot) | P1 从 MCP 一次性拉回、后续圆桌全部基于此的只读 KB |
| 临时层 (temp KB layer) | P3.5 人补充的内容,session 内可见,不写永久 KB |
| kb-diff | P7 候选写回的改动集,人审后可选写入永久 KB |
| session_id | 本次圆桌的唯一 ID,snapshot 和最终版登记的键 |

## 附录 B. 文件落盘约定

| 产物 | 默认路径 |
|---|---|
| 技术方案 | `<prd-dir>/../design/<prd-basename>.tech-design.md` |
| 任务拆解 | `<prd-dir>/../design/<prd-basename>.plan.md` |
| kb-diff | `<prd-dir>/../design/<prd-basename>.kb-diff.md` |
| snapshot | `.xteam/<session-id>/snapshot.json` |

用户可通过 `--out <dir>` 覆盖默认路径。`.xteam/` 始终在仓库根。
