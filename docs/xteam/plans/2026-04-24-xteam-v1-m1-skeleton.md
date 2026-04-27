# xTeam v1 · M1 Skeleton Walkthrough Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 xTeam Phase 0 → Phase 2 的核心骨架能跑通:命令启动、PRD 校验、KB fixture 加载(暂不接真 MCP)、architect draft 一次。产出可执行的 `/xteam-design` 命令,能把一份合法 PRD 变成 v0 tech-design.md(用假的 KB fixture)。

**Architecture:** Python 工具函数(`xteam_lib/` 包)+ Markdown skills(主对话 Claude 按 skill 编排)+ JSON Schema 契约文件。Python 负责确定性 I/O、schema 校验、snapshot、阈值计算、度量。Claude 负责调度、prompt 拼装、subagent 派发(通过 Task 工具)、合并决策。

**Tech Stack:** Python 3.11+ / `jsonschema` / `pyyaml` / `pytest` / `pytest-mock`. 插件内 Python 模块组织为 `xteam_lib/`,测试 `tests/xteam/unit/`。

**Spec 引用:** `docs/xteam/specs/2026-04-22-xteam-design.md`(757 行,本计划的唯一真相源)。

**M1 范围边界(YAGNI):**
- 只做 Phase 0(PRD 校验)→ Phase 1(KB 加载,**仅从 fixture 读**,不接 MCP)→ Phase 2(architect draft)
- 不做 Round 1/2、P3.5、P5、P6 plan-composer、P7 KB 写回——那些在 M2/M3
- 不做 resume 命令、度量面板、黄金测试集——M3
- Subagent 仅 architect 一个,且只用 draft mode
- MCP 真实接入延后到 M2(M1 用本地 fixture 文件模拟 KB 返回)

---

## File Structure

### 新建文件(全部新建,不改原有 skills/agents/commands)

```
/Users/sean/xlab/ai/xteam/
├── commands/
│   └── xteam-design.md                              # 入口 slash command
├── skills/
│   └── xteam-design/
│       ├── SKILL.md                                  # 主持人 skill(仅 P0/P1/P2)
│       └── must-answer-items.md                      # 11 项必答项清单
├── agents/
│   └── xteam-agent-architect.md                     # architect subagent prompt(draft mode)
├── schemas/xteam/
│   ├── prd.schema.json                               # PRD 结构化模板
│   ├── kb-snapshot.schema.json                       # KB 快照结构
│   ├── must-answer-state.schema.json                 # 必答项状态
│   └── architect-draft-output.schema.json            # architect draft 返回结构
├── templates/xteam/
│   └── prd-template.md                               # 给 PM 用的 PRD 模板样例
├── xteam_lib/                                        # Python 工具包
│   ├── __init__.py
│   ├── prd.py                                        # PRD 解析 + 校验
│   ├── kb.py                                         # KB fixture 加载 + 角色切片
│   ├── must_answer.py                                # 必答项 applicability 判定
│   ├── snapshot.py                                   # snapshot 读写
│   ├── schema_validate.py                            # 统一 schema 校验入口
│   ├── session.py                                    # session_id 生成 + 路径
│   └── errors.py                                     # 自定义异常 + 退出码
├── tests/xteam/
│   ├── conftest.py                                   # pytest fixtures 入口
│   ├── fixtures/
│   │   ├── prd/
│   │   │   ├── valid-minimal.md
│   │   │   ├── valid-with-legacy-module.md
│   │   │   ├── invalid-missing-fields.md
│   │   │   └── idea-not-prd.md
│   │   └── kb/
│   │       ├── module-comment.yaml
│   │       └── module-feed.yaml
│   └── unit/
│       ├── test_prd_parse.py
│       ├── test_prd_validate.py
│       ├── test_kb_load.py
│       ├── test_kb_slicing.py
│       ├── test_must_answer_applicability.py
│       ├── test_schema_validate.py
│       ├── test_snapshot_roundtrip.py
│       └── test_session_paths.py
├── pyproject.toml                                    # Python 项目配置
└── .xteam/                                           # 运行时目录(gitignored)
    └── .gitkeep
```

### 不改的文件

- 原有 `skills/*`(brainstorming / writing-plans / test-driven-development 等)
- 原有 `agents/code-reviewer.md`
- 原有 `commands/{brainstorm,execute-plan,write-plan}.md`
- `.claude-plugin/plugin.json`(M1 不改插件元信息,M2/M3 再改)

### 文件职责边界

| 文件 | 唯一职责 |
|---|---|
| `commands/xteam-design.md` | slash command 定义,描述如何调用 skill |
| `skills/xteam-design/SKILL.md` | 主持人策略:P0→P1→P2 的编排逻辑(用自然语言) |
| `skills/xteam-design/must-answer-items.md` | 11 项必答项唯一真相源(内容与 spec §2.2 一致) |
| `agents/xteam-agent-architect.md` | architect subagent prompt(含 draft / merge 双模,M1 只用 draft) |
| `schemas/xteam/*.schema.json` | 所有 JSON I/O 契约 |
| `templates/xteam/prd-template.md` | 给用户参考的 PRD 模板 |
| `xteam_lib/prd.py` | PRD 解析 + schema 校验 + "是否 idea/技术方案"的启发式判别 |
| `xteam_lib/kb.py` | 读 fixture KB、按角色切片、M2 时替换为真 MCP |
| `xteam_lib/must_answer.py` | 根据 PRD 涉及模块和业务类型判定每项 `applicable` |
| `xteam_lib/snapshot.py` | snapshot JSON 读写 |
| `xteam_lib/schema_validate.py` | 通用 schema 校验,统一错误 |
| `xteam_lib/session.py` | session_id 生成(UUID)、路径管理(`.xteam/<id>/`) |
| `xteam_lib/errors.py` | `PRDInvalid` `KBUnreachable` `SnapshotCorrupt` 等异常 + 退出码常量 |

---

## Task List

**Task order rationale:** 自底向上——先测 Python 工具函数(TDD),再写 schema / prompt / skill(Markdown 类,不走测试但要 schema 校验),最后拼成 `/xteam-design` 命令跑一次端到端冒烟。每个任务结束都 commit。

---

### Task 1: Python 项目基建

**Files:**
- Create: `pyproject.toml`
- Create: `xteam_lib/__init__.py`
- Create: `tests/xteam/__init__.py`
- Create: `tests/xteam/unit/__init__.py`
- Create: `tests/xteam/conftest.py`

- [ ] **Step 1: 创建 pyproject.toml**

```toml
[project]
name = "xteam"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "jsonschema>=4.20",
    "pyyaml>=6.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-mock>=3.12",
]

[tool.pytest.ini_options]
testpaths = ["tests/xteam"]
python_files = "test_*.py"
python_classes = "Test*"
python_functions = "test_*"
```

- [ ] **Step 2: 创建空包文件**

`xteam_lib/__init__.py`:
```python
"""xTeam support library — deterministic I/O, validation, state management.

Orchestration (LLM reasoning, merging, prompt composition) lives in SKILL.md.
"""
__version__ = "0.1.0"
```

`tests/xteam/__init__.py`:
```python
```

`tests/xteam/unit/__init__.py`:
```python
```

- [ ] **Step 3: 创建 conftest.py**

`tests/xteam/conftest.py`:
```python
from pathlib import Path

import pytest


@pytest.fixture
def fixtures_dir() -> Path:
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def tmp_xteam_root(tmp_path: Path) -> Path:
    """Root for .xteam/<session>/ paths during tests."""
    root = tmp_path / ".xteam"
    root.mkdir()
    return root
```

- [ ] **Step 4: 安装依赖并验证 pytest 运行**

Run: `cd /Users/sean/xlab/ai/xteam && python3 -m pip install -e ".[dev]"`
Expected: 安装成功。

Run: `cd /Users/sean/xlab/ai/xteam && python3 -m pytest tests/xteam -v`
Expected: `no tests ran` 或 collected 0 items(尚无测试)。

- [ ] **Step 5: Commit**

```bash
cd /Users/sean/xlab/ai/xteam
git add pyproject.toml xteam_lib/__init__.py tests/xteam/__init__.py tests/xteam/unit/__init__.py tests/xteam/conftest.py
git commit -m "feat(xteam): initialize Python project scaffolding

Adds pyproject.toml with jsonschema + pyyaml runtime deps and
pytest dev deps. Creates xteam_lib package (orchestration tooling)
and tests/xteam layout (unit tests + fixtures) per spec §7.2."
```

---

### Task 2: 异常与退出码

**Files:**
- Create: `xteam_lib/errors.py`
- Create: `tests/xteam/unit/test_errors.py`

- [ ] **Step 1: Write the failing test**

`tests/xteam/unit/test_errors.py`:
```python
from xteam_lib.errors import (
    EXIT_BAD_INPUT,
    EXIT_KB_UNREACHABLE,
    KBUnreachable,
    PRDInvalid,
    SnapshotCorrupt,
    XTeamError,
)


def test_exit_codes_are_stable_integers():
    assert EXIT_BAD_INPUT == 2
    assert EXIT_KB_UNREACHABLE == 3


def test_all_xteam_errors_inherit_base():
    assert issubclass(PRDInvalid, XTeamError)
    assert issubclass(KBUnreachable, XTeamError)
    assert issubclass(SnapshotCorrupt, XTeamError)


def test_error_carries_message_and_exit_code():
    err = PRDInvalid("missing field: goal")
    assert str(err) == "missing field: goal"
    assert err.exit_code == EXIT_BAD_INPUT

    err2 = KBUnreachable("mcp timeout")
    assert err2.exit_code == EXIT_KB_UNREACHABLE
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/xteam/unit/test_errors.py -v`
Expected: FAIL with `ModuleNotFoundError: xteam_lib.errors`.

- [ ] **Step 3: Write minimal implementation**

`xteam_lib/errors.py`:
```python
"""Exit codes and custom exceptions for xTeam.

Exit codes are stable (used by hooks/scripts to decide recovery actions).
Adding codes is backward-compatible; changing existing values is not.
"""

EXIT_BAD_INPUT = 2
EXIT_KB_UNREACHABLE = 3
EXIT_SNAPSHOT_CORRUPT = 4
EXIT_AGENT_FAILURE = 5


class XTeamError(Exception):
    exit_code = 1

    def __init__(self, message: str):
        super().__init__(message)


class PRDInvalid(XTeamError):
    exit_code = EXIT_BAD_INPUT


class KBUnreachable(XTeamError):
    exit_code = EXIT_KB_UNREACHABLE


class SnapshotCorrupt(XTeamError):
    exit_code = EXIT_SNAPSHOT_CORRUPT


class AgentFailure(XTeamError):
    exit_code = EXIT_AGENT_FAILURE
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/xteam/unit/test_errors.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add xteam_lib/errors.py tests/xteam/unit/test_errors.py
git commit -m "feat(xteam): add stable exit codes and error hierarchy

Exit codes are part of the public contract (hooks/scripts may branch
on them). Errors are typed so failure paths in skills can decide
whether to retry, snapshot-and-exit, or escalate to the user."
```

---

### Task 3: session_id + 路径管理

**Files:**
- Create: `xteam_lib/session.py`
- Create: `tests/xteam/unit/test_session_paths.py`

- [ ] **Step 1: Write the failing test**

`tests/xteam/unit/test_session_paths.py`:
```python
from pathlib import Path

import pytest

from xteam_lib.session import Session, new_session_id


def test_new_session_id_is_unique_uuid_shape():
    a = new_session_id()
    b = new_session_id()
    assert a != b
    assert len(a) == 36
    assert a.count("-") == 4


def test_session_paths_are_under_xteam_root(tmp_xteam_root: Path):
    sid = new_session_id()
    session = Session(sid, root=tmp_xteam_root)
    assert session.dir == tmp_xteam_root / sid
    assert session.snapshot_path == tmp_xteam_root / sid / "snapshot.json"


def test_session_dir_is_created_lazily(tmp_xteam_root: Path):
    sid = new_session_id()
    session = Session(sid, root=tmp_xteam_root)
    assert not session.dir.exists()
    session.ensure_dir()
    assert session.dir.is_dir()


def test_session_rejects_traversal_in_id(tmp_xteam_root: Path):
    with pytest.raises(ValueError, match="invalid session id"):
        Session("../evil", root=tmp_xteam_root)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/xteam/unit/test_session_paths.py -v`
Expected: FAIL with `ModuleNotFoundError: xteam_lib.session`.

- [ ] **Step 3: Write minimal implementation**

`xteam_lib/session.py`:
```python
"""Session identity and filesystem layout.

A session represents one end-to-end xteam-design invocation. Its state
lives under `.xteam/<session-id>/` at the repo root by default, but
tests pass a custom root.
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from pathlib import Path

_VALID_ID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def new_session_id() -> str:
    return str(uuid.uuid4())


@dataclass(frozen=True)
class Session:
    id: str
    root: Path

    def __post_init__(self):
        if not _VALID_ID.match(self.id):
            raise ValueError(f"invalid session id: {self.id!r}")

    @property
    def dir(self) -> Path:
        return self.root / self.id

    @property
    def snapshot_path(self) -> Path:
        return self.dir / "snapshot.json"

    def ensure_dir(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/xteam/unit/test_session_paths.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add xteam_lib/session.py tests/xteam/unit/test_session_paths.py
git commit -m "feat(xteam): add session id + filesystem layout

Session ids are UUID4. The frozen dataclass rejects path traversal
attempts (regex-validated on construction). Tests use a tmp_path
root; production uses .xteam/ at repo root."
```

---

### Task 4: JSON Schema · PRD 结构化模板

**Files:**
- Create: `schemas/xteam/prd.schema.json`

- [ ] **Step 1: Write the schema**

`schemas/xteam/prd.schema.json`:
```json
{
  "$schema": "https://json-schema.org/draft-07/schema#",
  "title": "xTeam PRD",
  "description": "Structured PRD format accepted by /xteam-design. v1 is frontmatter YAML + Markdown body. This schema validates the parsed frontmatter.",
  "type": "object",
  "required": [
    "title",
    "background",
    "goal",
    "user_scenarios",
    "features",
    "metrics",
    "out_of_scope",
    "involved_modules"
  ],
  "additionalProperties": false,
  "properties": {
    "title": { "type": "string", "minLength": 1, "maxLength": 200 },
    "background": { "type": "string", "minLength": 20 },
    "goal": { "type": "string", "minLength": 10 },
    "user_scenarios": {
      "type": "array",
      "minItems": 1,
      "items": { "type": "string", "minLength": 5 }
    },
    "features": {
      "type": "array",
      "minItems": 1,
      "items": {
        "type": "object",
        "required": ["id", "summary"],
        "additionalProperties": false,
        "properties": {
          "id": { "type": "string", "pattern": "^F[0-9]+$" },
          "summary": { "type": "string", "minLength": 5 },
          "priority": {
            "type": "string",
            "enum": ["P0", "P1", "P2"]
          }
        }
      }
    },
    "metrics": {
      "type": "array",
      "minItems": 1,
      "items": { "type": "string", "minLength": 3 }
    },
    "out_of_scope": {
      "type": "array",
      "items": { "type": "string" }
    },
    "involved_modules": {
      "type": "array",
      "minItems": 1,
      "items": {
        "type": "object",
        "required": ["name", "kind"],
        "additionalProperties": false,
        "properties": {
          "name": { "type": "string", "minLength": 1 },
          "kind": { "type": "string", "enum": ["legacy", "new", "shared"] },
          "touches_core_feature": { "type": "boolean" }
        }
      }
    },
    "business_type": {
      "type": "string",
      "enum": ["content_social", "transaction_payment", "b_enterprise", "mixed"],
      "description": "Used to gate content_safety / cache_strategy / hotspot must-answer items."
    }
  }
}
```

- [ ] **Step 2: 验证 schema 本身格式合法**

Run:
```bash
python3 -c "
import json
from jsonschema import Draft7Validator
with open('schemas/xteam/prd.schema.json') as f:
    schema = json.load(f)
Draft7Validator.check_schema(schema)
print('schema OK')
"
```
Expected: `schema OK`.

- [ ] **Step 3: Commit**

```bash
git add schemas/xteam/prd.schema.json
git commit -m "feat(xteam): define PRD structured schema

Enforces the 'structured template (hard constraint)' input policy
from spec §3 P0. Key additions vs brainstorming-time spec: explicit
'involved_modules[].kind' (legacy|new|shared) to drive
compat_and_isolation applicability, and 'business_type' to gate
content/social-specific must-answer items."
```

---

### Task 5: Schema 统一校验入口

**Files:**
- Create: `xteam_lib/schema_validate.py`
- Create: `tests/xteam/unit/test_schema_validate.py`

- [ ] **Step 1: Write the failing test**

`tests/xteam/unit/test_schema_validate.py`:
```python
from pathlib import Path

import pytest

from xteam_lib.schema_validate import validate_against, SchemaNotFound


REPO = Path(__file__).parents[3]


def test_validates_minimal_prd_frontmatter_payload():
    payload = {
        "title": "Add comment reactions",
        "background": "Users want to express reactions beyond like.",
        "goal": "Ship 6 reactions with content-safety gating.",
        "user_scenarios": ["User taps react on a comment"],
        "features": [{"id": "F1", "summary": "Reaction picker UI"}],
        "metrics": ["reaction dau uplift"],
        "out_of_scope": [],
        "involved_modules": [
            {"name": "comment", "kind": "legacy", "touches_core_feature": True}
        ],
    }
    validate_against(payload, "prd")  # no exception


def test_rejects_prd_missing_required_field():
    payload = {"title": "x"}
    with pytest.raises(ValueError, match="required"):
        validate_against(payload, "prd")


def test_unknown_schema_raises_schema_not_found():
    with pytest.raises(SchemaNotFound):
        validate_against({}, "nonexistent")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/xteam/unit/test_schema_validate.py -v`
Expected: FAIL with `ModuleNotFoundError: xteam_lib.schema_validate`.

- [ ] **Step 3: Write minimal implementation**

`xteam_lib/schema_validate.py`:
```python
"""Single entry point for JSON schema validation.

All xteam I/O contracts live in schemas/xteam/<name>.schema.json.
Callers pass the short name (e.g. "prd"); this module resolves the file
and runs jsonschema Draft-07 validation.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft7Validator, ValidationError


_SCHEMAS_DIR = Path(__file__).parents[1] / "schemas" / "xteam"


class SchemaNotFound(FileNotFoundError):
    pass


@lru_cache(maxsize=None)
def _load(name: str) -> Draft7Validator:
    path = _SCHEMAS_DIR / f"{name}.schema.json"
    if not path.exists():
        raise SchemaNotFound(f"schema not found: {path}")
    with path.open() as f:
        schema = json.load(f)
    Draft7Validator.check_schema(schema)
    return Draft7Validator(schema)


def validate_against(payload: Any, schema_name: str) -> None:
    """Raise ValueError with joined error messages if invalid."""
    validator = _load(schema_name)
    errors = sorted(validator.iter_errors(payload), key=lambda e: e.absolute_path)
    if errors:
        msgs = [_format(e) for e in errors]
        raise ValueError("schema validation failed: " + "; ".join(msgs))


def _format(err: ValidationError) -> str:
    loc = ".".join(str(p) for p in err.absolute_path) or "<root>"
    return f"{loc}: {err.message}"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/xteam/unit/test_schema_validate.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add xteam_lib/schema_validate.py tests/xteam/unit/test_schema_validate.py
git commit -m "feat(xteam): add unified schema validation entrypoint

validate_against(payload, schema_name) is the single way callers
assert JSON structure. Draft-07 cached per schema name. Errors are
aggregated into one ValueError so callers see all problems at once."
```

---

### Task 6: PRD 解析 · frontmatter + body 切分

**Files:**
- Create: `xteam_lib/prd.py`
- Create: `tests/xteam/unit/test_prd_parse.py`
- Create: `tests/xteam/fixtures/prd/valid-minimal.md`

- [ ] **Step 1: Create valid fixture PRD**

`tests/xteam/fixtures/prd/valid-minimal.md`:
```markdown
---
title: Add comment reactions
background: |
  Currently users can only "like" comments. We want 6 emoji reactions
  to match peer products and increase engagement in threads.
goal: Ship 6 reactions (like / love / laugh / wow / sad / angry) with content-safety gating within one sprint.
user_scenarios:
  - "User long-presses a comment and picks a reaction."
  - "Author sees per-reaction counts on their comments."
features:
  - id: F1
    summary: Reaction picker UI on comment cards
    priority: P0
  - id: F2
    summary: Aggregated count display
    priority: P1
metrics:
  - "Reaction DAU ratio ≥ 15% among commenters"
  - "Reaction API p99 ≤ 100ms"
out_of_scope:
  - Custom emoji uploads
  - Reactions on replies (handled in a later phase)
involved_modules:
  - name: comment
    kind: legacy
    touches_core_feature: true
  - name: feed
    kind: legacy
    touches_core_feature: false
business_type: content_social
---

# Add Comment Reactions

## Background

...
```

- [ ] **Step 2: Write the failing test**

`tests/xteam/unit/test_prd_parse.py`:
```python
from pathlib import Path

import pytest

from xteam_lib.prd import parse_prd


def test_parse_extracts_frontmatter_and_body(fixtures_dir: Path):
    prd = parse_prd(fixtures_dir / "prd" / "valid-minimal.md")
    assert prd.frontmatter["title"] == "Add comment reactions"
    assert prd.frontmatter["business_type"] == "content_social"
    assert len(prd.frontmatter["features"]) == 2
    assert prd.body.startswith("# Add Comment Reactions")


def test_parse_fails_without_frontmatter(tmp_path: Path):
    bad = tmp_path / "no-fm.md"
    bad.write_text("# Just a heading\n\nno frontmatter here.\n")
    with pytest.raises(ValueError, match="frontmatter"):
        parse_prd(bad)


def test_parse_fails_with_unclosed_frontmatter(tmp_path: Path):
    bad = tmp_path / "bad-fm.md"
    bad.write_text("---\ntitle: x\n\nbody without closing fence\n")
    with pytest.raises(ValueError, match="frontmatter"):
        parse_prd(bad)
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python3 -m pytest tests/xteam/unit/test_prd_parse.py -v`
Expected: FAIL with `ModuleNotFoundError: xteam_lib.prd`.

- [ ] **Step 4: Write minimal implementation**

`xteam_lib/prd.py`:
```python
"""PRD parsing and validation.

Input format (v1 hard-constrained):
  ---
  <YAML frontmatter matching schemas/xteam/prd.schema.json>
  ---
  # <free-form Markdown body>

parse_prd(path) -> PRD splits the two halves, YAML-loads the frontmatter,
but does NOT yet schema-validate (see validate_prd).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class PRD:
    frontmatter: dict[str, Any]
    body: str
    source_path: Path


def parse_prd(path: Path) -> PRD:
    text = path.read_text()
    if not text.startswith("---\n"):
        raise ValueError(f"missing frontmatter opener in {path}")
    rest = text[4:]
    end = rest.find("\n---\n")
    if end == -1:
        raise ValueError(f"unclosed frontmatter in {path}")
    fm_raw = rest[:end]
    body = rest[end + 5 :]
    try:
        fm = yaml.safe_load(fm_raw) or {}
    except yaml.YAMLError as e:
        raise ValueError(f"invalid YAML frontmatter in {path}: {e}") from e
    return PRD(frontmatter=fm, body=body.lstrip(), source_path=path)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python3 -m pytest tests/xteam/unit/test_prd_parse.py -v`
Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
git add xteam_lib/prd.py tests/xteam/unit/test_prd_parse.py tests/xteam/fixtures/prd/valid-minimal.md
git commit -m "feat(xteam): add PRD frontmatter+body parser

Splits YAML frontmatter from Markdown body. Validation is deferred
to a separate call (validate_prd in next commit) so parse errors
and schema errors have distinct error paths. Fixture uses the
content/social scenario with a legacy module."
```

---

### Task 7: PRD Schema 校验 + "idea vs PRD" 启发式拒绝

**Files:**
- Modify: `xteam_lib/prd.py`
- Create: `tests/xteam/unit/test_prd_validate.py`
- Create: `tests/xteam/fixtures/prd/invalid-missing-fields.md`
- Create: `tests/xteam/fixtures/prd/idea-not-prd.md`

- [ ] **Step 1: Create invalid fixtures**

`tests/xteam/fixtures/prd/invalid-missing-fields.md`:
```markdown
---
title: Half-baked feature
goal: Do something
---

just a body
```

`tests/xteam/fixtures/prd/idea-not-prd.md`:
```markdown
---
title: "想法:加个 AI 评论助手"
background: idea
goal: TBD
user_scenarios: []
features: []
metrics: []
out_of_scope: []
involved_modules: []
---

# AI Comment Assistant Idea

we should add an AI comment thing. not sure how yet. maybe like a button?
```

- [ ] **Step 2: Write the failing test**

`tests/xteam/unit/test_prd_validate.py`:
```python
from pathlib import Path

import pytest

from xteam_lib.errors import PRDInvalid
from xteam_lib.prd import parse_prd, validate_prd


def test_valid_prd_passes(fixtures_dir: Path):
    prd = parse_prd(fixtures_dir / "prd" / "valid-minimal.md")
    validate_prd(prd)  # no raise


def test_missing_required_fields_raises(fixtures_dir: Path):
    prd = parse_prd(fixtures_dir / "prd" / "invalid-missing-fields.md")
    with pytest.raises(PRDInvalid) as exc:
        validate_prd(prd)
    msg = str(exc.value)
    # each missing top-level field shows up in one message
    assert "background" in msg
    assert "user_scenarios" in msg
    assert "features" in msg


def test_idea_style_prd_is_rejected_as_too_thin(fixtures_dir: Path):
    """When features=[] or user_scenarios=[], treat as 'idea, not PRD'."""
    prd = parse_prd(fixtures_dir / "prd" / "idea-not-prd.md")
    with pytest.raises(PRDInvalid, match="appears to be an idea"):
        validate_prd(prd)
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python3 -m pytest tests/xteam/unit/test_prd_validate.py -v`
Expected: FAIL with `ImportError: cannot import name 'validate_prd'`.

- [ ] **Step 4: Add validate_prd to prd.py**

Append to `xteam_lib/prd.py`:
```python
from xteam_lib.errors import PRDInvalid
from xteam_lib.schema_validate import validate_against


def validate_prd(prd: PRD) -> None:
    """Schema-validate plus heuristic 'is this really a PRD?' check.

    Raises PRDInvalid with actionable messages for the user.
    """
    try:
        validate_against(prd.frontmatter, "prd")
    except ValueError as e:
        raise PRDInvalid(str(e)) from e

    fm = prd.frontmatter
    # Heuristic: schema passed min sizes, but content is vacuous.
    if not fm.get("features") or not fm.get("user_scenarios"):
        raise PRDInvalid(
            "PRD appears to be an idea, not a shippable spec "
            "(features or user_scenarios empty). "
            "Use superpowers:brainstorming to shape it first."
        )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python3 -m pytest tests/xteam/unit/test_prd_validate.py -v`
Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
git add xteam_lib/prd.py tests/xteam/unit/test_prd_validate.py tests/xteam/fixtures/prd/invalid-missing-fields.md tests/xteam/fixtures/prd/idea-not-prd.md
git commit -m "feat(xteam): add PRD validation + idea-vs-PRD rejection

validate_prd combines schema validation with a heuristic check
per spec §5.3 (reject 1: 'PRD is actually an idea'). The
schema's minItems=1 on features/user_scenarios fires first;
the heuristic is kept as a defense-in-depth second check for
the case where users pass schema-passing but vacuous arrays."
```

---

### Task 8: KB snapshot schema

**Files:**
- Create: `schemas/xteam/kb-snapshot.schema.json`

- [ ] **Step 1: Write the schema**

`schemas/xteam/kb-snapshot.schema.json`:
```json
{
  "$schema": "https://json-schema.org/draft-07/schema#",
  "title": "xTeam KB Snapshot",
  "description": "Session KB snapshot — result of P1 MCP pre-fetch, or M1 fixture load. Immutable within a session; temp layer overlays are kept separately.",
  "type": "object",
  "required": ["fetched_at", "modules"],
  "additionalProperties": false,
  "properties": {
    "fetched_at": { "type": "string", "format": "date-time" },
    "source": {
      "type": "string",
      "enum": ["mcp", "fixture"],
      "description": "M1 uses fixture; M2 switches to mcp."
    },
    "modules": {
      "type": "object",
      "additionalProperties": {
        "type": "object",
        "required": ["module_profile"],
        "additionalProperties": false,
        "properties": {
          "module_profile": {
            "type": "object",
            "required": ["tech_stack"],
            "additionalProperties": true,
            "properties": {
              "tech_stack": { "type": "string" },
              "data_stores": { "type": "array", "items": { "type": "string" } },
              "capacity": { "type": "string" },
              "test_strategy": { "type": "string" }
            }
          },
          "recent_incidents": {
            "type": "array",
            "items": { "type": "object", "additionalProperties": true }
          },
          "relevant_adrs": {
            "type": "array",
            "items": { "type": "object", "additionalProperties": true }
          },
          "historical_pitfalls": {
            "type": "array",
            "items": { "type": "object", "additionalProperties": true }
          },
          "conventions": {
            "type": "object",
            "additionalProperties": true
          }
        }
      }
    }
  }
}
```

- [ ] **Step 2: 验证 schema 合法**

Run:
```bash
python3 -c "
import json
from jsonschema import Draft7Validator
Draft7Validator.check_schema(json.load(open('schemas/xteam/kb-snapshot.schema.json')))
print('OK')
"
```
Expected: `OK`.

- [ ] **Step 3: Commit**

```bash
git add schemas/xteam/kb-snapshot.schema.json
git commit -m "feat(xteam): define KB snapshot schema

Mirrors spec §4.2 per-module structure. The 'source' field
distinguishes M1 fixture mode from M2 live MCP mode so tests
can catch accidentally-live calls in unit tests."
```

---

### Task 9: KB fixture 加载

**Files:**
- Create: `xteam_lib/kb.py`
- Create: `tests/xteam/fixtures/kb/module-comment.yaml`
- Create: `tests/xteam/fixtures/kb/module-feed.yaml`
- Create: `tests/xteam/unit/test_kb_load.py`

- [ ] **Step 1: Create KB fixtures**

`tests/xteam/fixtures/kb/module-comment.yaml`:
```yaml
module_profile:
  tech_stack: "Go 1.22 + gRPC, MySQL 8, Redis 7"
  data_stores:
    - "MySQL: comments (sharded by post_id)"
    - "Redis: comment:{post_id} list cache, TTL 10min"
  capacity: "peak ~50k QPS read / ~2k write"
  test_strategy: "integration tests via docker-compose; load tests nightly"
historical_pitfalls:
  - id: P-2024-07
    categories: ["schema", "migration"]
    summary: "Adding user_id index without online DDL caused 4min lag spike."
  - id: P-2025-02
    categories: ["hotspot", "cache"]
    summary: "Celebrity thread melted Redis shard; added local cache."
conventions:
  data:
    - "All comment tables use soft-delete (deleted_at)."
  security:
    - "PII never logged; user_id hashed in analytics."
  testing:
    - "Every new API gets a contract test in tests/contract/."
recent_incidents: []
relevant_adrs:
  - id: ADR-0031
    title: "Comment shard key chose post_id over user_id"
    categories: ["data"]
```

`tests/xteam/fixtures/kb/module-feed.yaml`:
```yaml
module_profile:
  tech_stack: "Go 1.22, Kafka, ClickHouse"
  data_stores:
    - "ClickHouse: user_feed_events (append-only)"
  capacity: "peak ~100k events/s"
  test_strategy: "replay golden event streams"
historical_pitfalls: []
conventions: {}
recent_incidents:
  - id: I-2025-09
    categories: ["performance"]
    summary: "ClickHouse merge lag during promo event."
relevant_adrs: []
```

- [ ] **Step 2: Write the failing test**

`tests/xteam/unit/test_kb_load.py`:
```python
from pathlib import Path

import pytest

from xteam_lib.errors import KBUnreachable
from xteam_lib.kb import load_kb_from_fixtures


def test_loads_requested_modules(fixtures_dir: Path):
    snap = load_kb_from_fixtures(
        modules=["comment", "feed"],
        fixtures_dir=fixtures_dir / "kb",
    )
    assert snap.source == "fixture"
    assert set(snap.modules.keys()) == {"comment", "feed"}
    assert snap.modules["comment"]["module_profile"]["tech_stack"].startswith("Go")
    assert snap.modules["feed"]["module_profile"]["data_stores"][0].startswith("ClickHouse")
    assert snap.fetched_at  # ISO timestamp


def test_missing_fixture_is_kb_unreachable(fixtures_dir: Path):
    with pytest.raises(KBUnreachable, match="no fixture"):
        load_kb_from_fixtures(
            modules=["nonexistent"],
            fixtures_dir=fixtures_dir / "kb",
        )


def test_snapshot_validates_against_schema(fixtures_dir: Path):
    """load_kb_from_fixtures must return a snapshot that passes its own schema."""
    from xteam_lib.schema_validate import validate_against

    snap = load_kb_from_fixtures(
        modules=["comment"],
        fixtures_dir=fixtures_dir / "kb",
    )
    validate_against(snap.to_dict(), "kb-snapshot")
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python3 -m pytest tests/xteam/unit/test_kb_load.py -v`
Expected: FAIL with `ModuleNotFoundError: xteam_lib.kb`.

- [ ] **Step 4: Write minimal implementation**

`xteam_lib/kb.py`:
```python
"""KB snapshot loading.

M1: load from YAML fixture files under tests/xteam/fixtures/kb/.
M2: replace load_kb_from_fixtures with a live MCP adapter that
    satisfies the same KBSnapshot interface.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import yaml

from xteam_lib.errors import KBUnreachable


@dataclass(frozen=True)
class KBSnapshot:
    fetched_at: str
    source: str  # "fixture" | "mcp"
    modules: dict[str, dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def load_kb_from_fixtures(
    modules: Iterable[str], fixtures_dir: Path
) -> KBSnapshot:
    """Load each module's YAML fixture. Raise KBUnreachable if any is missing."""
    collected: dict[str, dict[str, Any]] = {}
    for name in modules:
        path = fixtures_dir / f"module-{name}.yaml"
        if not path.exists():
            raise KBUnreachable(f"no fixture for module {name!r} at {path}")
        with path.open() as f:
            collected[name] = yaml.safe_load(f) or {}
    return KBSnapshot(
        fetched_at=_now_iso(),
        source="fixture",
        modules=collected,
    )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python3 -m pytest tests/xteam/unit/test_kb_load.py -v`
Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
git add xteam_lib/kb.py tests/xteam/fixtures/kb/module-comment.yaml tests/xteam/fixtures/kb/module-feed.yaml tests/xteam/unit/test_kb_load.py
git commit -m "feat(xteam): add KB fixture loader

M1 loads from local YAML fixtures; raises KBUnreachable for missing
modules (same exception path as a real MCP failure in M2). Snapshot
round-trips through the kb-snapshot schema, confirming the fixture
contract matches what M2 will need to produce."
```

---

### Task 10: KB 角色切片

**Files:**
- Modify: `xteam_lib/kb.py`
- Create: `tests/xteam/unit/test_kb_slicing.py`

- [ ] **Step 1: Write the failing test**

`tests/xteam/unit/test_kb_slicing.py`:
```python
from pathlib import Path

import pytest

from xteam_lib.kb import load_kb_from_fixtures, slice_for_role


@pytest.fixture
def snap(fixtures_dir: Path):
    return load_kb_from_fixtures(["comment", "feed"], fixtures_dir / "kb")


def test_architect_gets_full_snapshot(snap):
    sliced = slice_for_role(snap, "architect")
    assert sliced == snap.modules  # architect sees everything


def test_data_role_filters_to_data_concerns(snap):
    sliced = slice_for_role(snap, "data")
    comment = sliced["comment"]
    # data_stores kept
    assert "data_stores" in comment["module_profile"]
    # capacity dropped (perf concern)
    assert "capacity" not in comment["module_profile"]
    # only schema/migration pitfalls kept
    pfs = comment["historical_pitfalls"]
    assert all(
        {"schema", "migration"} & set(p.get("categories", []))
        for p in pfs
    )


def test_perf_role_filters_to_perf_concerns(snap):
    sliced = slice_for_role(snap, "perf")
    comment = sliced["comment"]
    assert "capacity" in comment["module_profile"]
    assert "data_stores" not in comment["module_profile"]
    pfs = comment["historical_pitfalls"]
    assert all(
        {"hotspot", "cache"} & set(p.get("categories", []))
        for p in pfs
    )


def test_security_role_filters_to_security_concerns(snap):
    sliced = slice_for_role(snap, "security")
    comment = sliced["comment"]
    # conventions.security kept; conventions.data dropped
    convs = comment.get("conventions", {})
    assert "security" in convs
    assert "data" not in convs


def test_qa_role_filters_to_qa_concerns(snap):
    sliced = slice_for_role(snap, "qa")
    comment = sliced["comment"]
    assert "test_strategy" in comment["module_profile"]
    assert "conventions" in comment
    assert "testing" in comment["conventions"]
    assert "data" not in comment["conventions"]


def test_unknown_role_raises(snap):
    with pytest.raises(ValueError, match="unknown role"):
        slice_for_role(snap, "coder")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/xteam/unit/test_kb_slicing.py -v`
Expected: FAIL with `ImportError: cannot import name 'slice_for_role'`.

- [ ] **Step 3: Extend xteam_lib/kb.py**

Append to `xteam_lib/kb.py`:
```python
# --- Role slicing ---
#
# Canonical slicing rules (spec §4.3). The table is data, not code,
# so new roles / fields only require editing _SLICE_RULES below.

_SLICE_RULES: dict[str, dict[str, Any]] = {
    "architect": {"all": True},
    "data": {
        "module_profile_keys": ["tech_stack", "data_stores"],
        "pitfall_categories": ["schema", "migration"],
        "convention_keys": ["data"],
        "adr_categories": ["data"],
        "keep_incidents_categories": [],
    },
    "perf": {
        "module_profile_keys": ["tech_stack", "capacity"],
        "pitfall_categories": ["hotspot", "cache"],
        "convention_keys": [],
        "adr_categories": [],
        "keep_incidents_categories": ["performance"],
    },
    "security": {
        "module_profile_keys": ["tech_stack"],
        "pitfall_categories": ["auth", "data_leak"],
        "convention_keys": ["security"],
        "adr_categories": ["security"],
        "keep_incidents_categories": [],
    },
    "qa": {
        "module_profile_keys": ["tech_stack", "test_strategy"],
        "pitfall_categories": [],
        "convention_keys": ["testing"],
        "adr_categories": [],
        "keep_incidents_categories": ["regression"],
    },
}


def slice_for_role(snap: KBSnapshot, role: str) -> dict[str, dict[str, Any]]:
    if role not in _SLICE_RULES:
        raise ValueError(f"unknown role: {role!r}")
    rules = _SLICE_RULES[role]
    if rules.get("all"):
        return snap.modules

    result: dict[str, dict[str, Any]] = {}
    for mod_name, mod_data in snap.modules.items():
        result[mod_name] = _slice_module(mod_data, rules)
    return result


def _slice_module(mod: dict[str, Any], rules: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    # module_profile: keep whitelisted keys only
    profile = mod.get("module_profile", {})
    kept_profile = {k: v for k, v in profile.items() if k in rules["module_profile_keys"]}
    if kept_profile:
        out["module_profile"] = kept_profile
    # historical_pitfalls: filter by category
    pfs = [
        p
        for p in mod.get("historical_pitfalls", [])
        if set(p.get("categories", [])) & set(rules["pitfall_categories"])
    ]
    if pfs:
        out["historical_pitfalls"] = pfs
    # conventions: keep whitelisted subkeys
    convs = mod.get("conventions", {}) or {}
    kept_convs = {k: v for k, v in convs.items() if k in rules["convention_keys"]}
    if kept_convs:
        out["conventions"] = kept_convs
    # relevant_adrs: filter by category
    adrs = [
        a
        for a in mod.get("relevant_adrs", [])
        if set(a.get("categories", [])) & set(rules["adr_categories"])
    ]
    if adrs:
        out["relevant_adrs"] = adrs
    # recent_incidents: filter by category
    incs = [
        i
        for i in mod.get("recent_incidents", [])
        if set(i.get("categories", [])) & set(rules["keep_incidents_categories"])
    ]
    if incs:
        out["recent_incidents"] = incs
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/xteam/unit/test_kb_slicing.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add xteam_lib/kb.py tests/xteam/unit/test_kb_slicing.py
git commit -m "feat(xteam): add role-based KB slicing

Implements spec §4.3 slicing table as data (_SLICE_RULES dict).
Adding a role or field is a one-line change — no branching logic.
architect sees everything; reviewers see only their domain's
profile keys, pitfall categories, conventions, ADRs, incidents."
```

---

### Task 11: 必答项清单文件

**Files:**
- Create: `skills/xteam-design/must-answer-items.md`

- [ ] **Step 1: Write the canonical must-answer list**

`skills/xteam-design/must-answer-items.md`:
`````markdown
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
`````

- [ ] **Step 2: Commit**

```bash
git add skills/xteam-design/must-answer-items.md
git commit -m "feat(xteam): add canonical must-answer items list

Embedded YAML is the machine-readable source; prose below explains
applies_when semantics to the LLM reading the SKILL. 11 items total:
7 always-on, 1 legacy-module-gated, 3 content/social-gated
(spec §2.2)."
```

---

### Task 12: 必答项 applicability 判定

**Files:**
- Create: `xteam_lib/must_answer.py`
- Create: `tests/xteam/unit/test_must_answer_applicability.py`
- Create: `tests/xteam/fixtures/prd/valid-with-legacy-module.md`(已有 valid-minimal 覆盖;增加一个新模块场景)
- Create: `tests/xteam/fixtures/prd/valid-new-module-only.md`

- [ ] **Step 1: Create additional fixtures**

`tests/xteam/fixtures/prd/valid-new-module-only.md`:
```markdown
---
title: New recommendation widget (greenfield)
background: |
  We want to launch an independent recommendation widget in a new service,
  isolated from the existing feed.
goal: Ship a standalone rec widget with its own storage and API.
user_scenarios:
  - "User sees 'recommended for you' card below the feed."
features:
  - id: F1
    summary: Rec candidate generation service
    priority: P0
metrics:
  - "Rec CTR ≥ 8%"
out_of_scope:
  - Replacing existing feed ranker
involved_modules:
  - name: rec_widget
    kind: new
    touches_core_feature: false
business_type: content_social
---

# New Rec Widget
```

(`valid-with-legacy-module.md` is covered by `valid-minimal.md` already — skip creating a duplicate.)

- [ ] **Step 2: Write the failing test**

`tests/xteam/unit/test_must_answer_applicability.py`:
```python
from pathlib import Path

from xteam_lib.must_answer import MustAnswerItem, compute_applicability, load_canonical_items
from xteam_lib.prd import parse_prd


def test_canonical_list_has_11_items():
    items = load_canonical_items()
    assert len(items) == 11
    ids = {i.id for i in items}
    assert "schema" in ids
    assert "compat_and_isolation" in ids
    assert "hotspot" in ids


def test_always_items_always_applicable(fixtures_dir: Path):
    prd = parse_prd(fixtures_dir / "prd" / "valid-minimal.md")
    state = compute_applicability(prd, load_canonical_items())
    assert state["schema"].applicable is True
    assert state["api_contract"].applicable is True
    assert state["rollback"].applicable is True


def test_compat_applies_when_legacy_core_module_present(fixtures_dir: Path):
    prd = parse_prd(fixtures_dir / "prd" / "valid-minimal.md")
    # comment is kind=legacy + touches_core_feature=true
    state = compute_applicability(prd, load_canonical_items())
    assert state["compat_and_isolation"].applicable is True


def test_compat_skipped_when_only_new_modules(fixtures_dir: Path):
    prd = parse_prd(fixtures_dir / "prd" / "valid-new-module-only.md")
    state = compute_applicability(prd, load_canonical_items())
    assert state["compat_and_isolation"].applicable is False


def test_content_social_items_applicable_when_business_type_matches(fixtures_dir: Path):
    prd = parse_prd(fixtures_dir / "prd" / "valid-minimal.md")
    state = compute_applicability(prd, load_canonical_items())
    for key in ("content_safety", "cache_strategy", "hotspot"):
        assert state[key].applicable is True


def test_items_initial_status_is_missing(fixtures_dir: Path):
    prd = parse_prd(fixtures_dir / "prd" / "valid-minimal.md")
    state = compute_applicability(prd, load_canonical_items())
    for item in state.values():
        assert item.status == "missing"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python3 -m pytest tests/xteam/unit/test_must_answer_applicability.py -v`
Expected: FAIL with `ModuleNotFoundError: xteam_lib.must_answer`.

- [ ] **Step 4: Write minimal implementation**

`xteam_lib/must_answer.py`:
```python
"""Must-answer item applicability and status tracking.

The canonical list lives in skills/xteam-design/must-answer-items.md,
embedded as a YAML block between ```yaml fences. We parse that block
to avoid duplicating the definition.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import yaml

from xteam_lib.prd import PRD


_CANONICAL_MD = (
    Path(__file__).parents[1] / "skills" / "xteam-design" / "must-answer-items.md"
)

_YAML_BLOCK = re.compile(r"```yaml\n(.*?)```", re.DOTALL)

_VALID_STATUS = {"missing", "draft", "n/a"}


@dataclass
class MustAnswerItem:
    id: str
    applies_when: str
    owners: list[str]
    description: str
    applicable: bool = False
    status: str = "missing"


def load_canonical_items() -> list[MustAnswerItem]:
    text = _CANONICAL_MD.read_text()
    match = _YAML_BLOCK.search(text)
    if not match:
        raise RuntimeError(f"no yaml block in {_CANONICAL_MD}")
    data = yaml.safe_load(match.group(1))
    return [
        MustAnswerItem(
            id=item["id"],
            applies_when=item["applies_when"],
            owners=list(item["owners"]),
            description=item["description"],
        )
        for item in data["items"]
    ]


def compute_applicability(
    prd: PRD, items: Iterable[MustAnswerItem]
) -> dict[str, MustAnswerItem]:
    fm = prd.frontmatter
    has_legacy_core = any(
        m.get("kind") == "legacy" and m.get("touches_core_feature")
        for m in fm.get("involved_modules", [])
    )
    business_type = fm.get("business_type")

    state: dict[str, MustAnswerItem] = {}
    for item in items:
        # shallow copy to avoid mutating caller's list
        copy = MustAnswerItem(
            id=item.id,
            applies_when=item.applies_when,
            owners=list(item.owners),
            description=item.description,
        )
        copy.applicable = _evaluate(
            item.applies_when,
            has_legacy_core=has_legacy_core,
            business_type=business_type,
        )
        state[item.id] = copy
    return state


def _evaluate(
    applies_when: str, *, has_legacy_core: bool, business_type: str | None
) -> bool:
    if applies_when == "always":
        return True
    if applies_when == "involved_legacy_core_module":
        return has_legacy_core
    if applies_when == "business_type_content_social":
        return business_type == "content_social"
    raise ValueError(f"unknown applies_when: {applies_when!r}")
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python3 -m pytest tests/xteam/unit/test_must_answer_applicability.py -v`
Expected: 6 passed.

- [ ] **Step 6: Commit**

```bash
git add xteam_lib/must_answer.py tests/xteam/unit/test_must_answer_applicability.py tests/xteam/fixtures/prd/valid-new-module-only.md
git commit -m "feat(xteam): compute must-answer applicability from PRD

Parses the canonical YAML block out of must-answer-items.md (single
source of truth). Evaluates applies_when rules against PRD
frontmatter. New-module-only PRDs correctly skip
compat_and_isolation per spec §2.2.1."
```

---

### Task 13: Snapshot 读写

**Files:**
- Create: `xteam_lib/snapshot.py`
- Create: `tests/xteam/unit/test_snapshot_roundtrip.py`

- [ ] **Step 1: Write the failing test**

`tests/xteam/unit/test_snapshot_roundtrip.py`:
```python
from pathlib import Path

import pytest

from xteam_lib.errors import SnapshotCorrupt
from xteam_lib.session import Session, new_session_id
from xteam_lib.snapshot import Snapshot, load_snapshot, save_snapshot


def test_roundtrip(tmp_xteam_root: Path):
    session = Session(new_session_id(), root=tmp_xteam_root)
    snap = Snapshot(
        session_id=session.id,
        phase="P2",
        prd_path="/tmp/prd.md",
        kb_snapshot={"source": "fixture", "modules": {}},
        drafts={"v0": "hello"},
        must_answer_state={"schema": {"applicable": True, "status": "missing"}},
        open_questions_for_human=[],
        human_responses=[],
    )
    save_snapshot(session, snap)

    loaded = load_snapshot(session)
    assert loaded.phase == "P2"
    assert loaded.drafts["v0"] == "hello"
    assert loaded.must_answer_state["schema"]["applicable"] is True


def test_load_missing_file_raises(tmp_xteam_root: Path):
    session = Session(new_session_id(), root=tmp_xteam_root)
    with pytest.raises(FileNotFoundError):
        load_snapshot(session)


def test_corrupt_json_raises_snapshot_corrupt(tmp_xteam_root: Path):
    session = Session(new_session_id(), root=tmp_xteam_root)
    session.ensure_dir()
    session.snapshot_path.write_text("{ not valid json")
    with pytest.raises(SnapshotCorrupt):
        load_snapshot(session)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/xteam/unit/test_snapshot_roundtrip.py -v`
Expected: FAIL with `ModuleNotFoundError: xteam_lib.snapshot`.

- [ ] **Step 3: Write minimal implementation**

`xteam_lib/snapshot.py`:
```python
"""Session snapshot read/write.

Single JSON file per session. Schema lives in
schemas/xteam/snapshot.schema.json (added in a later task when the
full field set stabilizes). For M1 we roundtrip without schema
validation — validation is added when more phases write to the same
file.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from xteam_lib.errors import SnapshotCorrupt
from xteam_lib.session import Session


@dataclass
class Snapshot:
    session_id: str
    phase: str
    prd_path: str
    kb_snapshot: dict[str, Any]
    drafts: dict[str, str] = field(default_factory=dict)
    must_answer_state: dict[str, dict[str, Any]] = field(default_factory=dict)
    open_questions_for_human: list[str] = field(default_factory=list)
    human_responses: list[dict[str, Any]] = field(default_factory=list)
    last_error: str | None = None
    updated_at: str = ""


def save_snapshot(session: Session, snap: Snapshot) -> None:
    session.ensure_dir()
    snap.updated_at = (
        datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )
    session.snapshot_path.write_text(json.dumps(asdict(snap), indent=2, ensure_ascii=False))


def load_snapshot(session: Session) -> Snapshot:
    path = session.snapshot_path
    if not path.exists():
        raise FileNotFoundError(path)
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        raise SnapshotCorrupt(f"invalid JSON in {path}: {e}") from e
    return Snapshot(**data)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/xteam/unit/test_snapshot_roundtrip.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add xteam_lib/snapshot.py tests/xteam/unit/test_snapshot_roundtrip.py
git commit -m "feat(xteam): add snapshot save/load with corruption handling

M1 snapshot has the fields P0-P2 need; P3+ fields (rounds,
changelog) will be added when those phases implement them.
Corrupt JSON surfaces as SnapshotCorrupt so resume logic can
tell 'no snapshot yet' (FileNotFoundError) from 'snapshot broken'."
```

---

### Task 14: architect agent prompt(draft mode)

**Files:**
- Create: `schemas/xteam/architect-draft-output.schema.json`
- Create: `agents/xteam-agent-architect.md`

- [ ] **Step 1: Write the output schema**

`schemas/xteam/architect-draft-output.schema.json`:
```json
{
  "$schema": "https://json-schema.org/draft-07/schema#",
  "title": "Architect agent · draft mode output",
  "description": "Structured return from architect subagent when mode=draft (Phase 2).",
  "type": "object",
  "required": ["mode", "tech_design_markdown", "must_answer_updates"],
  "additionalProperties": false,
  "properties": {
    "mode": { "const": "draft" },
    "tech_design_markdown": { "type": "string", "minLength": 100 },
    "must_answer_updates": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["id", "status"],
        "additionalProperties": false,
        "properties": {
          "id": { "type": "string" },
          "status": { "type": "string", "enum": ["missing", "draft", "n/a"] }
        }
      }
    },
    "open_questions_for_human": {
      "type": "array",
      "items": { "type": "string" }
    }
  }
}
```

- [ ] **Step 2: Write the architect agent prompt**

`agents/xteam-agent-architect.md`:
`````markdown
---
name: xteam-agent-architect
description: |
  xTeam architect subagent. In v1 supports `mode: draft` only — produce
  the first-cut technical design from a structured PRD and a KB context.
  Future modes (merge, review) will be added in M2.
model: inherit
---

You are the xTeam Architect agent. You work in one pass per invocation;
you have no memory across invocations. Your caller is the xTeam
orchestrator (a Claude Code session running the `xteam-design` skill).

# Mode · draft

You are invoked in `mode: draft` during Phase 2. Your inputs (from the
orchestrator's prompt text) are:

1. The parsed PRD frontmatter + body
2. A KB snapshot (full, not sliced — you get everything)
3. The initial `must_answer_items` state (all `missing`)

Your output **must be a single fenced JSON block** matching
`schemas/xteam/architect-draft-output.schema.json`. The
`tech_design_markdown` field inside contains the human-readable design.

## Required sections in `tech_design_markdown`

Use these exact H2 headings (the orchestrator's regression tests check for them):

- `## 方案概述`
- `## 数据模型`
- `## 接口契约`
- `## 失败处理`
- `## 迁移与灰度`
- `## 监控与告警`
- `## 限流与回滚`

Plus these **only when the corresponding must-answer item is applicable**
(check the `must_answer_items` input):

- `## 版本兼容与隔离` — when `compat_and_isolation` is applicable
- `## 内容安全` — when `content_safety` is applicable
- `## 缓存策略` — when `cache_strategy` is applicable
- `## 热点与峰值` — when `hotspot` is applicable

## `must_answer_updates`

For each section you write with substantive content, emit
`{"id": "<must-answer id>", "status": "draft"}`. For sections you
deliberately skipped because they're `n/a`, emit
`{"id": "<id>", "status": "n/a"}`. Do not touch items you haven't
addressed (leave them as `missing`).

## Hard constraints

- Every decision must cite at least one KB fact (module_profile,
  historical_pitfalls, ADR) when one is relevant. If KB has no data,
  write `*(KB: 无先例)*` inline.
- Never propose sunsetting legacy interfaces — old clients are
  permanently coexisting (spec §2.2.1 implicit agreement). If you feel
  tempted, emit an `open_questions_for_human` entry instead.
- If you need information the PRD + KB don't provide to produce a
  responsible design, emit it to `open_questions_for_human` rather than
  guessing.
- Do NOT output anything before or after the JSON fence. No preamble,
  no trailing commentary.

## Output shape

````
```json
{
  "mode": "draft",
  "tech_design_markdown": "## 方案概述\n...\n## 数据模型\n...\n",
  "must_answer_updates": [
    {"id": "schema", "status": "draft"},
    {"id": "compat_and_isolation", "status": "draft"}
  ],
  "open_questions_for_human": [
    "冷热分离阈值 30d vs 90d?KB 无先例,需业务决策。"
  ]
}
```
````

# Mode · merge (PLACEHOLDER — not implemented in M1)

A future M2 task will extend this file with `mode: merge` behavior.
For now, if invoked with `mode: merge`, respond with:

````
```json
{"error": "merge mode not implemented in M1"}
```
````
`````

- [ ] **Step 3: Validate schema file is well-formed**

Run:
```bash
python3 -c "
import json
from jsonschema import Draft7Validator
Draft7Validator.check_schema(json.load(open('schemas/xteam/architect-draft-output.schema.json')))
print('OK')
"
```
Expected: `OK`.

- [ ] **Step 4: Commit**

```bash
git add schemas/xteam/architect-draft-output.schema.json agents/xteam-agent-architect.md
git commit -m "feat(xteam): add architect agent (draft mode) + output schema

Single prompt file will host draft/merge/... modes per spec §1.2.1
(role × mode orthogonality). M1 only implements draft mode; merge
returns an explicit placeholder error to catch premature invocation.
Required H2 sections in tech_design_markdown let the M1 integration
test assert structural presence without comparing exact wording."
```

---

### Task 15: PRD 模板 · 给 PM 参考

**Files:**
- Create: `templates/xteam/prd-template.md`

- [ ] **Step 1: Write the template**

`templates/xteam/prd-template.md`:
```markdown
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
```

- [ ] **Step 2: Commit**

```bash
git add templates/xteam/prd-template.md
git commit -m "docs(xteam): add PRD template for PMs

Matches prd.schema.json exactly. Comments explain what each field
drives (e.g. touches_core_feature gates compat_and_isolation)."
```

---

### Task 16: xteam-design skill SKILL.md(M1 范围:P0/P1/P2)

**Files:**
- Create: `skills/xteam-design/SKILL.md`

- [ ] **Step 1: Write the skill**

`skills/xteam-design/SKILL.md`:
````markdown
---
name: xteam-design
description: |
  M1 scope — Phase 0 PRD intake, Phase 1 KB fetch (fixture in M1, MCP in M2),
  Phase 2 architect draft. Terminates with a v0 tech-design markdown file
  and a snapshot. Rounds / mid-check / converge / outputs / writeback are
  out of scope for M1 (see docs/xteam/plans/ for M2 & M3).
---

# xTeam Design · M1 Skeleton Walkthrough

Your role in this skill is the **orchestrator** (spec §1.2): a Claude
Code session running this playbook, not a subagent. You call Python
utilities for deterministic work and dispatch the architect subagent
via the Task tool.

## When to use

Invoked by `/xteam-design <prd-path>`. If the user invokes this skill
directly without a path, ask for the PRD path once and stop if they
don't provide one.

## M1 execution

### Phase 0 — Intake

1. Run `python3 -c "from xteam_lib.prd import parse_prd, validate_prd; \
   p = parse_prd('<prd-path>'); validate_prd(p); \
   print('OK', p.frontmatter['title'])"`.
   - On non-zero exit: show the error (it comes from `PRDInvalid`),
     explain what's missing, and stop. Do not proceed.

2. On success, generate a session id and prepare paths:
   ```
   python3 -c "from xteam_lib.session import Session, new_session_id; \
     from pathlib import Path; \
     sid = new_session_id(); \
     s = Session(sid, root=Path('.xteam')); s.ensure_dir(); \
     print(sid)"
   ```

### Phase 1 — Context

1. Run the applicability computer:
   ```
   python3 -c "
   from xteam_lib.prd import parse_prd
   from xteam_lib.must_answer import compute_applicability, load_canonical_items
   import json
   p = parse_prd('<prd-path>')
   state = compute_applicability(p, load_canonical_items())
   print(json.dumps({k: {'applicable': v.applicable, 'status': v.status, 'description': v.description} for k, v in state.items()}, ensure_ascii=False))
   "
   ```
   Inspect the result. Note which `must_answer` items are `applicable=true`.

2. **M1: load KB from fixtures** (not MCP). For each module in
   `prd.frontmatter.involved_modules`, verify
   `tests/xteam/fixtures/kb/module-<name>.yaml` exists. If any is
   missing, tell the user:
   > `M1 uses fixture KB. Module <name> has no fixture at
   > tests/xteam/fixtures/kb/module-<name>.yaml. Create one modelled
   > on module-comment.yaml and retry.`
   and stop.

3. Load the snapshot:
   ```
   python3 -c "
   from xteam_lib.kb import load_kb_from_fixtures
   from pathlib import Path
   snap = load_kb_from_fixtures(
     modules=[<modules from prd>],
     fixtures_dir=Path('tests/xteam/fixtures/kb'),
   )
   print('KB snapshot:', sorted(snap.modules.keys()))
   "
   ```

4. Build a snapshot object (via `xteam_lib.snapshot.save_snapshot`)
   capturing session_id, phase='P1', the PRD path, kb snapshot dict,
   and the must-answer state.

### Phase 2 — Draft

1. Compose the architect subagent prompt:
   - Full PRD frontmatter + body
   - Full KB snapshot (architect gets everything per §4.3)
   - Must-answer state (applicable items flagged)
   - Instruction: `mode: draft` per agent spec

2. Dispatch via the **Task** tool with `subagent_type: xteam-agent-architect`.

3. The subagent returns a fenced JSON block. Extract it and validate
   against schema:
   ```
   python3 -c "
   import json, sys
   from xteam_lib.schema_validate import validate_against
   payload = json.loads(open('/tmp/architect-out.json').read())
   validate_against(payload, 'architect-draft-output')
   print('OK')
   "
   ```
   On `ValueError`: re-dispatch once with the error message appended
   to the prompt. If second attempt also fails, snapshot and exit
   with error.

4. Write the draft to disk at
   `<prd-dir>/../design/<prd-basename>.tech-design.md` (create the
   `design/` directory if missing).

5. Update snapshot with `drafts.v0 = tech_design_markdown`,
   merge `must_answer_updates` into state, phase='P2-complete'.
   `save_snapshot`.

6. Tell the user:
   > `M1 draft complete. Output: <path>. must-answer state: N applicable, M draft, K missing. Rounds of review, mid-check, and final plan.md are M2/M3.`

## Files referenced

- `skills/xteam-design/must-answer-items.md` — canonical list
- `agents/xteam-agent-architect.md` — subagent prompt
- `schemas/xteam/*` — all I/O schemas
- `xteam_lib/` — deterministic helpers

## Not in M1

- Reviewer agents (data/perf/security/qa) — M2
- Round 1/2, P3.5, P5 — M2
- plan-composer + plan.md — M2
- kb-diff + P7 writeback — M3
- Resume / metrics / golden test suite — M3
````

- [ ] **Step 2: Commit**

```bash
git add skills/xteam-design/SKILL.md
git commit -m "feat(xteam): add xteam-design skill (M1 scope)

Orchestrates Phase 0 (intake) → P1 (fixture KB load) → P2 (architect
draft). Each phase's Python calls are inlined so the LLM executing
this skill can see exactly what to run. M2/M3 scope explicitly listed
as 'Not in M1' to prevent drift during execution."
```

---

### Task 17: slash command 入口

**Files:**
- Create: `commands/xteam-design.md`

- [ ] **Step 1: Write the command definition**

`commands/xteam-design.md`:
```markdown
---
description: "xTeam v1 · run the design roundtable on a structured PRD (M1: P0/P1/P2 only)"
---

Use the `xteam-design` skill to process the PRD at the path provided.

If `$ARGUMENTS` is empty, ask the user for a PRD path and stop if they
don't provide one.

Otherwise, invoke the `xteam-design` skill with `$ARGUMENTS` as the PRD
path.
```

- [ ] **Step 2: Commit**

```bash
git add commands/xteam-design.md
git commit -m "feat(xteam): add /xteam-design slash command (M1 entry)

Thin wrapper that forwards to the xteam-design skill. Prompts for
a path if invoked without arguments."
```

---

### Task 18: 端到端冒烟测试 · Python 级

**Files:**
- Create: `tests/xteam/unit/test_m1_smoke.py`

- [ ] **Step 1: Write the smoke test**

`tests/xteam/unit/test_m1_smoke.py`:
```python
"""End-to-end smoke test covering the Python side of M1 only.

The architect subagent dispatch happens in the skill (Markdown +
Task tool), which we can't exercise in unit tests. This file tests
that every deterministic step the skill invokes works in sequence.
"""
from pathlib import Path

from xteam_lib.kb import load_kb_from_fixtures
from xteam_lib.must_answer import compute_applicability, load_canonical_items
from xteam_lib.prd import parse_prd, validate_prd
from xteam_lib.session import Session, new_session_id
from xteam_lib.snapshot import Snapshot, save_snapshot, load_snapshot


def test_p0_p1_pipeline_runs_for_valid_prd(
    fixtures_dir: Path, tmp_xteam_root: Path
):
    # Phase 0
    prd = parse_prd(fixtures_dir / "prd" / "valid-minimal.md")
    validate_prd(prd)

    # Phase 1a: applicability
    state = compute_applicability(prd, load_canonical_items())
    applicable = {k for k, v in state.items() if v.applicable}
    assert "schema" in applicable
    assert "compat_and_isolation" in applicable
    assert "hotspot" in applicable

    # Phase 1b: KB
    module_names = [m["name"] for m in prd.frontmatter["involved_modules"]]
    snap = load_kb_from_fixtures(module_names, fixtures_dir / "kb")
    assert set(snap.modules.keys()) == set(module_names)

    # Phase 1c: snapshot
    session = Session(new_session_id(), root=tmp_xteam_root)
    ss = Snapshot(
        session_id=session.id,
        phase="P1-complete",
        prd_path=str(prd.source_path),
        kb_snapshot=snap.to_dict(),
        must_answer_state={
            k: {"applicable": v.applicable, "status": v.status}
            for k, v in state.items()
        },
    )
    save_snapshot(session, ss)

    # Reload and verify integrity
    loaded = load_snapshot(session)
    assert loaded.phase == "P1-complete"
    assert loaded.must_answer_state["compat_and_isolation"]["applicable"] is True
    assert "comment" in loaded.kb_snapshot["modules"]
```

- [ ] **Step 2: Run test**

Run: `python3 -m pytest tests/xteam/unit/test_m1_smoke.py -v`
Expected: 1 passed (depends on prior tasks' code).

- [ ] **Step 3: Run the full test suite to confirm no regressions**

Run: `python3 -m pytest tests/xteam -v`
Expected: All tests from Tasks 2, 3, 5, 6, 7, 9, 10, 12, 13, 18 pass. No failures.

- [ ] **Step 4: Commit**

```bash
git add tests/xteam/unit/test_m1_smoke.py
git commit -m "test(xteam): add Python-level M1 smoke test

Exercises the deterministic pipeline the skill invokes in sequence:
parse → validate → applicability → KB load → snapshot → reload.
The architect subagent dispatch lives in the skill Markdown and is
not covered here; an end-to-end skill test belongs in M2 alongside
real subagent integration."
```

---

### Task 19: .gitignore 与运行时目录

**Files:**
- Modify: `.gitignore`
- Create: `.xteam/.gitkeep`

- [ ] **Step 1: Inspect current .gitignore**

Run: `cat /Users/sean/xlab/ai/xteam/.gitignore`
Note: current content (copy for the edit).

- [ ] **Step 2: Edit .gitignore**

Append (do not remove anything existing):
```
# xTeam runtime state
.xteam/*
!.xteam/.gitkeep

# Python
__pycache__/
*.py[cod]
.pytest_cache/
*.egg-info/
```

- [ ] **Step 3: Create .xteam/.gitkeep**

Run:
```bash
mkdir -p /Users/sean/xlab/ai/xteam/.xteam
touch /Users/sean/xlab/ai/xteam/.xteam/.gitkeep
```

- [ ] **Step 4: Commit**

```bash
git add .gitignore .xteam/.gitkeep
git commit -m "chore(xteam): ignore runtime state + Python build artifacts

.xteam/ holds session-scoped snapshots (per spec §3.5) — tracked
only via .gitkeep. Python cache/build dirs added for completeness."
```

---

### Task 20: M1 verification

**Files:** (no new files)

- [ ] **Step 1: Full test suite green**

Run: `cd /Users/sean/xlab/ai/xteam && python3 -m pytest tests/xteam -v`
Expected: All tests pass; count = sum across Tasks 2, 3, 5, 6, 7, 9, 10, 12, 13, 18 (ballpark 25+ tests).

- [ ] **Step 2: Manual skill smoke run**

In Claude Code:
- Ensure plugin is reloaded (restart or use `/plugin reload` if available)
- Run: `/xteam-design tests/xteam/fixtures/prd/valid-minimal.md`
- Expected behavior:
  - Phase 0 reports "OK Add comment reactions"
  - Phase 1 prints KB snapshot for modules `['comment', 'feed']`
  - Phase 2 dispatches architect subagent (Task tool)
  - Subagent returns JSON block matching architect-draft-output schema
  - A file appears at `tests/xteam/fixtures/prd/../design/valid-minimal.tech-design.md`
  - A snapshot appears at `.xteam/<session-id>/snapshot.json`

- [ ] **Step 3: Run the schema validator on the produced tech-design JSON**

If the skill captured the raw architect JSON anywhere (e.g. in the snapshot's `drafts.v0` or a side-channel file), validate it:
```bash
python3 -c "
import json
from xteam_lib.schema_validate import validate_against
# Adjust path based on where the skill stored raw output
payload = json.loads(open('.xteam/<sid>/architect-draft.json').read())
validate_against(payload, 'architect-draft-output')
print('OK')
"
```
Expected: `OK`. (If the skill does not store raw JSON, skip this step and note it for M2 — future architect-merge work will need the raw JSON persisted.)

- [ ] **Step 4: Invalid PRD rejection check**

Run: `/xteam-design tests/xteam/fixtures/prd/idea-not-prd.md`
Expected: stops in Phase 0 with message mentioning "appears to be an idea".

- [ ] **Step 5: Commit any verification-only notes**

If issues found that require fixing: create follow-up tasks, do not commit broken code.
If verification passes: no commit needed — this task is a gate, not a deliverable.

---

## Self-Review

### 1. Spec coverage

Walk the spec and map each M1-in-scope requirement to a task:

| Spec requirement | M1 task(s) |
|---|---|
| §0 超出摘要 ("6 角色圆桌...") | Out of M1 scope — only architect in M1 |
| §1.1 流程图 Phase 0/1/2 | Task 16 skill |
| §1.2 三个角色层级 | Task 14 (architect), Task 16 (orchestrator) |
| §1.2.1 Role × Mode | Task 14 (architect double-mode placeholder) |
| §1.3 关键不变式 | Task 16 (orchestrator owns MCP/fixture), Task 14 (JSON out) |
| §2.1 共享输入 | Task 16 Phase 2 prompt composition |
| §2.2 必答项清单 11 项 | Task 11 canonical list, Task 12 applicability |
| §2.2.1 compat_and_isolation 详细 | Task 11 YAML + Task 14 section gating |
| §2.3 reviewer schema | Out of M1 — M2 |
| §2.4 architect draft/merge | Task 14 draft + placeholder merge |
| §2.5 plan-composer | Out of M1 — M2 |
| §3.1 状态机 | Task 16 (P0/P1/P2 only) |
| §3.2 失败处置 (M1 subset) | Task 2 exit codes, Task 7 PRD reject, Task 9 KB unreachable |
| §3.3 P3.5 | Out of M1 |
| §3.5 持久化 snapshot | Task 13 |
| §4.2 预抓策略 | Task 9 (fixtures) |
| §4.3 角色切片 | Task 10 |
| §4.5 KB 硬停 | Task 9 (KBUnreachable raises) |
| §5.1 失败总表 (M1 subset) | Tasks 2, 7, 9, 13 |
| §5.3 P0 拒绝 | Task 7 idea-vs-PRD heuristic |
| §6.2 主持人单元测试 | Tasks 2/3/5/6/7/9/10/12/13/18 |
| §7.2 文件布局 | All file-creating tasks |
| §8 实施清单 | This plan addresses M1 subset; M2/M3 remain |

**Gaps I'm accepting as out-of-M1-scope:** §2.3 reviewer schemas,
§2.4 merge mode (placeholder only), §2.5 plan-composer, §3.3 P3.5,
§3.4 P5, §4.4 kb-diff, §6.3 component tests, §6.4 golden suite,
§6.5 Go/No-Go metrics. These get their own M2/M3 plans.

### 2. Placeholder scan

Scanning for forbidden patterns (`TBD`, "implement later", "similar to
Task N", missing code blocks):

- Task 14 "mode: merge (PLACEHOLDER)" — this is **intentional** per
  YAGNI: spec §1.2.1 says merge is added when needed. The placeholder
  returns an explicit error, not silent behavior.
- Task 20 Step 3 mentions "if skill does not store raw JSON, skip this
  step and note it for M2" — this is actionable guidance, not a
  placeholder.

No TBDs found otherwise.

### 3. Type consistency

- `MustAnswerItem` fields (id, applies_when, owners, description,
  applicable, status) — used consistently in Tasks 11, 12, 18.
- `Session` fields (id, root, dir, snapshot_path) — Tasks 3, 13, 18.
- `Snapshot` fields (session_id, phase, prd_path, kb_snapshot, drafts,
  must_answer_state, open_questions_for_human, human_responses,
  last_error, updated_at) — Tasks 13, 18. **Checked:** test_m1_smoke
  creates Snapshot without `last_error` — correct (has default).
- `KBSnapshot` (fetched_at, source, modules, to_dict) — Tasks 9, 10, 18.
- `PRD` (frontmatter, body, source_path) — Tasks 6, 7, 12, 18.
- Schema names used in `validate_against`: `"prd"` (Task 5, 7),
  `"kb-snapshot"` (Task 9), `"architect-draft-output"` (Task 14, 20).
  All exist as files in Tasks 4, 8, 14.
- Error classes (`PRDInvalid`, `KBUnreachable`, `SnapshotCorrupt`,
  `AgentFailure`) — imported consistently.

All consistent. No renames detected between tasks.

---

## Execution Handoff

Plan complete and saved to `docs/xteam/plans/2026-04-24-xteam-v1-m1-skeleton.md`. Two execution options:

1. **Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration
2. **Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?