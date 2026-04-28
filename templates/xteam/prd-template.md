---
# 复制此文件并填写所有字段。每项都是必填(schema 会校验)。
# 文件命名建议:YYYY-MM-DD-<短标题>.md

title: <一句话标题,≤ 200 字>
background: |
  为什么要做这件事。背景、动机、数据支持。≥ 20 字。
goal: <本次要交付什么,一句话说清。≥ 10 字>

user_scenarios:
  - "<场景 1:用户做什么,在哪里做,预期得到什么>"
  - "<场景 2>"

features:
  - id: F1
    summary: <功能点简述 ≥ 5 字>
    priority: P0  # P0 | P1 | P2
  - id: F2
    summary: <...>
    priority: P1

metrics:
  - "<上线后用什么指标衡量成功。要可测量>"

out_of_scope:
  - "<明确不做什么>"

involved_modules:
  # 每个受影响的模块一项。
  # kind: legacy = 存量模块 / new = 新模块 / shared = 共享模块
  # touches_core_feature: 本次改动是否触碰该模块的核心功能(影响兼容必答项激活)
  - name: <模块名>
    kind: legacy
    touches_core_feature: true

business_type: content_social  # content_social | transaction_payment | b_enterprise | mixed
---

# <正文标题>

## 背景(可展开 background 字段)

...

## 用户故事(可展开 user_scenarios)

...

## 详细功能

### F1 · <...>

...

### F2 · <...>

...

## 不做的事

...
