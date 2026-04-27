# xTeam Must-Answer Items (canonical list)

> This file is the single source of truth for must-answer items.
> Code reads this via YAML frontmatter; prose explains intent to the LLM.
> Editing the YAML block below requires a regeneration of downstream tests.

```yaml
items:
  - id: schema
    applies_when: always
    owners: [architect, data]
    description: 数据模型(表/字段/索引/分片)
  - id: api_contract
    applies_when: always
    owners: [architect]
    description: 对外接口(入参/出参/错误码/幂等键)
  - id: failure_modes
    applies_when: always
    owners: [architect, qa]
    description: 失败处理(超时/重试/降级/补偿)
  - id: migration
    applies_when: always
    owners: [architect, data]
    description: 迁移方案(存量数据/灰度节奏)
  - id: observability
    applies_when: always
    owners: [architect, perf]
    description: 监控指标 + 告警阈值
  - id: rate_limit
    applies_when: always
    owners: [architect, perf]
    description: 限流/熔断策略
  - id: rollback
    applies_when: always
    owners: [architect, qa]
    description: 回滚方案 + 预案演练要求
  - id: compat_and_isolation
    applies_when: involved_legacy_core_module
    owners: [architect, data, qa]
    description: >
      版本兼容与隔离 — 仅当 PRD 涉及存量核心模块时必答。
      覆盖:影响面、兼容策略(向后兼容/并存/仅新版)、
      隔离手段(数据/流量/故障)、破坏性变更说明。
      不写老接口下线计划(老版本默认永久共存)。
  - id: content_safety
    applies_when: business_type_content_social
    owners: [architect, security]
    description: 内容合规与审核
  - id: cache_strategy
    applies_when: business_type_content_social
    owners: [architect, perf, data]
    description: 缓存策略(TTL、热点、穿透/雪崩)
  - id: hotspot
    applies_when: business_type_content_social
    owners: [architect, perf]
    description: 热点/峰值预估与应对
```

## Applicability 判定语义

`applies_when` 值到条件的映射(由 `xteam_lib/must_answer.py` 实现):

| 值 | 条件 |
|---|---|
| `always` | 无条件激活 |
| `involved_legacy_core_module` | PRD.involved_modules 中存在 `kind=legacy` 且 `touches_core_feature=true` 的项 |
| `business_type_content_social` | PRD.business_type == "content_social" |

Round 2 结束时,所有 `applicable=true` 的项必须是 `draft` 或 `n/a`——否则进 P5 人兜底。
