## 方案概述

为评论模块增加 6 种表情回应（like / love / laugh / wow / sad / angry），替代当前仅有的"点赞"功能。峰值写 3K QPS，回填仅 100 行历史数据。

**核心设计决策：**
- 新建独立表 comment_reactions + comment_reaction_counts，不修改现有评论表
- 分片键沿用 post_id（ADR-0031），与评论表共分片
- 三层缓存（L1 Caffeine TinyLFU → L2 Redis Hash → L3 MySQL 计数表）
- Write-behind + speculative Redis INCRBY + 失败补偿 HINCRBY
- Outbox 模式推送 Feed 事件到 Kafka
- Feature flag reaction_v1 控制全链路开关
- Shadow-ban phantom write + Kafka 审计事件
- 安全检查同步 200ms fail-closed + 异步深度分析

## 数据模型

### 新表：comment_reactions

```sql
CREATE TABLE comment_reactions (
  id BIGINT UNSIGNED NOT NULL COMMENT 'Snowflake distributed ID',
  comment_id BIGINT UNSIGNED NOT NULL,
  post_id BIGINT UNSIGNED NOT NULL,
  user_id BIGINT UNSIGNED NOT NULL,
  reaction_type TINYINT UNSIGNED NOT NULL COMMENT '1=like,2=love,3=laugh,4=wow,5=sad,6=angry',
  is_active TINYINT UNSIGNED NOT NULL DEFAULT 1,
  created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  PRIMARY KEY (id),
  UNIQUE KEY uk_comment_user_type (comment_id, user_id, reaction_type),
  KEY idx_comment_active (comment_id, is_active),
  KEY idx_user_comment (user_id, comment_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

UK 仅含 (comment_id, user_id, reaction_type)，每个自然键最多一行。写入使用 INSERT ON DUPLICATE KEY UPDATE is_active=1 实现 react，UPDATE is_active=0 实现 unreact。

**is_active vs deleted_at 惯例偏离说明：** Reaction toggle 频率高，布尔翻转比 soft-delete 语义更清晰，IODKU 单语句原子 toggle 仅需布尔列。

### 预聚合计数表：comment_reaction_counts

```sql
CREATE TABLE comment_reaction_counts (
  post_id BIGINT UNSIGNED NOT NULL COMMENT 'shard routing key',
  comment_id BIGINT UNSIGNED NOT NULL,
  reaction_type TINYINT UNSIGNED NOT NULL,
  count INT UNSIGNED NOT NULL DEFAULT 0,
  updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  PRIMARY KEY (post_id, comment_id, reaction_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

## 接口契约

gRPC CommentReactionService: AddReaction / RemoveReaction / GetReactions (batch max 50)。
服务端校验：reaction_type ∈ {1..6}，否则 INVALID_ARGUMENT。
鉴权：沿用现有 AuthInterceptor + JWT。

## 缓存策略

### Write-Behind + Speculative Redis Counter

写入路径：Client → 安全检查(sync 200ms) → Redis HINCRBY (speculative) → Buffer → MySQL batch
读取路径：Client → L1 TinyLFU(32k/30s) → L2 Redis Hash(10min) → L3 MySQL

**Buffer 参数：** flush 间隔 200ms，max batch 500 条，shutdown drain timeout 2s。
**各 pod 独立 flush 自己的 buffer**（无跨 pod 协调）。

**失败补偿：** DB 写入失败时执行补偿 HINCRBY -delta，确保 Redis 计数不漂移。

**Redis Key 分布：** rc:{comment_id} 无 hash-tag，自然分散 slot。热点 >1000/s 路由到独立 Redis 实例。

## 热点与峰值

Count-Min Sketch (pod-local, 4×4096, 50% decay/10s)。>500/s 自适应限流。>1000/s 热点隔离。

## 失败处理

降级阶梯含安全服务：
- L0 正常: 同步安全 + 异步深度分析
- L1 安全服务 p99 > 180ms: 告警准备切换
- L2 安全服务错误率 > 5%/1min: 启用本地规则引擎降级
- L3 安全服务完全不可用 > 5min: 全局写入熔断 503

Redis/MySQL 降级阶梯保持不变（Level 0-3）。

## 内容安全

- Shadow-ban: phantom write (accept, suppress persistence, viewer-only)
- **Phantom write 审计：** 每次发射 Kafka 审计事件 (hashed user_id, comment_id, reaction_type, reason=shadow_ban)，保留 1 年
- 安全检查 **fail-closed**：超时返回 UNAVAILABLE + Retry-After，异步链路仅用于深度分析
- Z-score 动态阈值 (SAD+ANGRY, μ+3σ)
- 限流：per-comment 200/min + per-IP/CIDR (IPv4 /24, IPv6 /48, ops 可配)

## 迁移与灰度

Phase 1 Schema → Phase 2 双写 → Phase 3 回填(100行) → Phase 4 灰度 → Phase 5 旧表退役

**回填后验证：** 立即执行 ad-hoc 对账查询，drift=0 后方可开始灰度。

### Canary Gates

| 阶段 | 流量 | 观测窗口 | 最小样本 | 通过条件 |
|------|------|----------|----------|----------|
| C1 | 5% | 10min | 100 req | err<0.1%, p99 达标 |
| C2 | 20% | 5min | 500 req | 同上 |
| C3 | 50% | 3min | 1000 req | 同上 |
| C4 | 100% | 1min | 2000 req | 同上 |

## 监控与告警

| 级别 | 读路径 | 写路径 |
|------|--------|--------|
| P1 | p99 > 150ms/2min | p99 > 350ms/2min |
| P2 | cache < 80%/10min | buffer > 2000 条 |
| P2 | - | |Redis-MySQL| > 50 |
| P3 | - | drift > 0.01% |

## 限流与回滚

限流：per-user 30/min write + 120/min read；per-comment 200/min；per-IP/CIDR (/24) 50/min。
软回滚：flag off → 停双写 → 服务回滚 → RENAME TABLE archived（90 天保留）。

## 版本兼容与隔离

like API 双写不变；新表独立；Redis 前缀 rc:/rv:；Feature flag 按区域。

## 可测试性

Contract (buf breaking + skeema diff + Pact)，Integration (Testcontainers)，场景矩阵 8 项，Feed golden fixtures。

## 对账机制

- **单 leader 节点**执行对账 cron（分布式锁选举）
- 周期：每 4 小时全量扫描
- 最大漂移窗口：24h，稳态目标 <0.01%
- 告警：单 comment_id |Redis-MySQL| > 50

## 预案演练 (Chaos Engineering Runbook)

### 故障场景矩阵

| # | 场景 | 注入方式 | 预期行为 | Pass/Fail |
|---|------|----------|----------|-----------|
| 1 | Redis 主节点宕机 | Chaos Mesh PodChaos / iptables | 降级 DB 直读；buffer 暂存；P99 升高 <500ms | 无数据丢失；告警 ≤30s |
| 2 | MySQL 写入超时 | 注入 sleep 至 DB proxy | 补偿 HINCRBY；请求重试；buffer 积压告警 | Redis 偏差 ≤ 补偿窗口 |
| 3 | 安全服务超时 (>200ms) | 注入延迟 sidecar | fail-closed 拒绝写入 503 | 无脏数据写入 |
| 4 | 安全服务完全不可用 | Kill pod | L3 熔断；全局写入拒绝 | 熔断 ≤60s；恢复后自动解除 |
| 5 | Pod 崩溃 (buffer 未 flush) | Kill -9 | buffer 丢失；对账 4h 内修正 | 漂移 ≤ 丢失批次；24h 归零 |
| 6 | 网络分区 (pod↔Redis) | iptables drop | 降级 DB 直读/写；恢复后对账 | 无重复计数 |
| 7 | 对账 leader 故障 | Kill leader | 新 leader ≤30s 选举 | 下一周期正常 |

### 演练节奏
- 上线前：覆盖全部 7 场景（必须通过）
- 稳态：每季度 1 次全量 + 每月 1 次随机
- 重大变更后：重跑相关场景
