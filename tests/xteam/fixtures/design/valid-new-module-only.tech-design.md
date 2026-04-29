## 方案概述

新建独立推荐 Widget 服务 `rec_widget`，与现有 Feed 完全隔离，拥有独立存储和 API。技术栈：Go + Redis + MySQL *(KB: module_profile.tech_stack)*。

### 架构总览

```
┌─────────┐      ┌───────────────┐      ┌────────────┐      ┌──────────────┐
│ Client  │─────▶│  API Gateway  │─────▶│ rec_widget │─────▶│ rec_widget_db│
└─────────┘      └───────────────┘      │  (Go)      │─────▶│ (MySQL)      │
                                        │            │      └──────────────┘
                                        │            │─────▶┌──────────────┐
                                        └────────────┘      │ rec_cache    │
                                                            │ (Redis)      │
                                                            └──────────────┘
```

核心流程：
1. 候选生成（离线/近线）：定时任务生成用户推荐候选集，写入 `rec_widget_db` *(KB: data_stores[0].purpose)*
2. 召回排序（在线）：请求到达时从 Redis 缓存读取候选集 *(KB: data_stores[1].purpose)*，执行轻量排序后返回
3. 曝光/点击日志回写 MySQL，供后续模型迭代

性能目标：p99 ≤ 50ms，峰值 10000 QPS *(KB: capacity)*。

## 数据模型

### MySQL — rec_widget_db

```sql
-- 推荐候选表
CREATE TABLE rec_candidates (
  id           BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  user_id      BIGINT UNSIGNED NOT NULL,
  content_id   BIGINT UNSIGNED NOT NULL,
  score        FLOAT NOT NULL DEFAULT 0,
  reason_code  VARCHAR(64) NOT NULL DEFAULT '',
  status       TINYINT NOT NULL DEFAULT 1 COMMENT '1=active, 0=dismissed',
  created_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  INDEX idx_user_status_score (user_id, status, score DESC),
  INDEX idx_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 交互日志表
CREATE TABLE rec_interactions (
  id           BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  user_id      BIGINT UNSIGNED NOT NULL,
  content_id   BIGINT UNSIGNED NOT NULL,
  action       ENUM('impression','click','dismiss') NOT NULL,
  created_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_user_action (user_id, action, created_at),
  INDEX idx_content (content_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

预计数据量：10M rows/month 增长 *(KB: capacity.data_volume)*。需要在第 3 个月前规划分区策略或归档方案（见 open_questions）。

### Redis — rec_cache

```
Key:   rec:user:{user_id}:candidates
Value: JSON array of top-N candidates (sorted by score desc)
TTL:   300s (5min)
```

## 接口契约

API 风格：RESTful JSON over HTTP *(KB: conventions.api_style)*
错误码格式：REC_XXXX *(KB: conventions.error_code_format)*

### GET /api/v1/rec/widget

获取当前用户推荐列表。

**Request:**
```
GET /api/v1/rec/widget?limit=5&offset=0
Headers:
  Authorization: Bearer {token}
  X-Request-ID: {uuid}
```

**Response 200:**
```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "items": [
      {
        "content_id": 123456,
        "score": 0.95,
        "reason": "基于你的浏览历史",
        "content_snapshot": {
          "title": "...",
          "cover_url": "...",
          "author_name": "..."
        }
      }
    ],
    "has_more": true,
    "request_id": "uuid"
  }
}
```

**Error responses:**
| HTTP | code | error_code | 说明 |
|------|------|------------|------|
| 401  | -1   | REC_1001   | 未授权 |
| 429  | -1   | REC_2001   | 限流 |
| 500  | -1   | REC_5001   | 内部错误 |
| 503  | -1   | REC_5003   | 服务降级 |

### POST /api/v1/rec/widget/interaction

上报曝光/点击/dismiss 事件。

**Request:**
```json
{
  "content_id": 123456,
  "action": "click"
}
```

**Response 200:**
```json
{"code": 0, "message": "ok"}
```

## 失败处理

| 故障场景 | 检测方式 | 应对策略 | 用户感知 |
|---------|---------|---------|----------|
| Redis 不可用 | 连接超时 >20ms | 降级直查 MySQL (带 limit)，同时触发告警 | 延迟轻微上升，功能可用 |
| MySQL 不可用 | 连接池耗尽 | 返回空列表 + REC_5003，触发 P1 告警 | Widget 区域展示"暂无推荐" |
| 候选生成延迟 | 监控最近一次生成时间 >2h | 使用上一批次缓存候选集 | 推荐新鲜度下降但无感知 |
| 上游内容服务超时 | 请求超时 >100ms | 返回候选 ID 列表但不含 content_snapshot | 客户端降级展示 |
| Redis 缓存击穿 | 单 key QPS 异常 | singleflight + 短 TTL 兜底 | 无感知 |

*(KB: pitfalls 为空，无先例)*

## 迁移与灰度

由于是全新服务 *(KB: module kind=new)*，无需数据迁移。采用以下灰度策略：

### Phase 1 — 内部验证 (Day 1-3)
- 仅内部员工可见
- 验证端到端链路正确性
- 确认监控告警有效

### Phase 2 — 小流量灰度 (Day 4-10)
- 1% → 5% → 10% 用户
- 观察 p99 延迟、错误率、CTR 指标
- 每阶段至少观察 24h

### Phase 3 — 放量 (Day 11-20)
- 10% → 30% → 50% → 100%
- 关注 MySQL 写入量和 Redis 内存增长

回滚触发条件：
- p99 > 100ms 持续 5min
- 错误率 > 1% 持续 3min
- 候选生成延迟 > 4h

## 监控与告警

### Metrics
| 指标 | 类型 | 告警阈值 |
|------|------|---------|
| rec_widget_request_latency_p99 | Histogram | > 50ms (P2), > 100ms (P1) |
| rec_widget_request_qps | Counter | > 12000 (P2, 超预期峰值 20%) |
| rec_widget_error_rate | Gauge | > 0.5% (P2), > 1% (P1) |
| rec_widget_cache_hit_rate | Gauge | < 80% (P2) |
| rec_widget_candidate_freshness | Gauge | > 2h since last gen (P2) |
| rec_widget_ctr | Gauge | 低于 8% 连续 7d (P2, 业务指标) |
| rec_widget_db_connections | Gauge | > 80% pool (P1) |
| rec_widget_redis_memory | Gauge | > 70% max (P2) |

### Logging
- 请求日志：request_id, user_id, latency, status_code
- 错误日志：error_code, stack trace, context
- 采样率：正常 10%，错误 100%

### Tracing
- 全链路 trace 接入（OpenTelemetry），span 覆盖：API 入口 → Cache → DB → 上游调用

## 限流与回滚

### 限流策略
- 全局限流：10000 QPS *(KB: capacity.peak_qps)*
- 单用户限流：50 req/min（防刷）
- 实现方式：Redis 滑动窗口计数器
- 超限返回 429 + REC_2001

### 回滚方案
- **服务回滚**：基于容器平台 rolling update，保留最近 3 个版本镜像可秒级回滚
- **灰度开关**：Feature flag 控制 Widget 展示，关闭后客户端不请求该接口
- **数据回滚**：候选表支持按批次标记 status=0 软删除，无需物理删除

*(KB: ADRs 为空，无先例)*

## 内容安全

推荐候选来源于平台已发布内容（已通过内容审核），但仍需以下防护：

1. **候选生成阶段过滤**：排除被标记为违规/下架的内容 ID
2. **在线召回阶段二次校验**：请求内容服务时确认 content_status=published
3. **用户举报联动**：dismiss 事件中 reason=inappropriate 时，触发内容复审流程
4. **黑名单机制**：维护全局内容黑名单（Redis Set），候选生成和在线召回均做过滤

*(KB: 无先例)*

## 缓存策略

基于 Redis 缓存热推荐结果 *(KB: data_stores[1].purpose)*：

| 缓存层 | Key 模式 | TTL | 淘汰策略 |
|--------|---------|-----|----------|
| 用户候选集 | `rec:user:{uid}:candidates` | 300s | 写时更新 + TTL 过期 |
| 内容快照 | `rec:content:{cid}:snapshot` | 600s | TTL 过期 |
| 全局热门兜底 | `rec:global:hot` | 60s | 定时刷新 |

### 缓存一致性
- 候选生成完成后主动刷新用户缓存
- 内容下架时通过消息队列异步删除相关缓存 key
- 缓存穿透防护：空结果缓存 30s + 布隆过滤器

### 冷启动
- 新用户/缓存 miss 时返回全局热门兜底列表
- 全局热门列表每分钟由定时任务刷新

## 热点与峰值

峰值 QPS：10000 *(KB: capacity.peak_qps)*

### 热点场景
1. **热门内容**：单条内容被大量推荐 → 内容快照缓存独立，不影响用户维度查询
2. **新用户涌入**：注册高峰导致大量冷启动 → 全局热门兜底列表预热，独立于用户缓存
3. **定时任务风暴**：候选生成批量写入 Redis → 分批写入 + 随机 jitter 打散

### 应对措施
- 读请求：Redis 缓存 + singleflight 合并回源
- 写请求（交互日志）：本地 buffer 批量写入 MySQL，500ms 或 100 条触发 flush
- 弹性扩容：基于 QPS/CPU 指标自动 HPA，扩容阈值 70% peak_qps
- 预案：极端流量时降级为返回全局热门（无个性化），保证可用性

*(KB: 无先例)*
