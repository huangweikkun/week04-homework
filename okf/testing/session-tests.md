---
type: Playbook
title: login_demo 会话测试
description: login_demo 登录会话单元测试的测试路径与运行命令。
status: stable
tags: [login_demo, testing, session]
generated: { by: pi-coding-agent/deepseek-v4-pro, at: 2026-11-14T04:20:27Z }
sources:
  - id: test-file
    resource: ../login_demo/tests/auth/test_session.py
    title: login_demo 会话单元测试文件
  - id: testing-guide
    resource: ../login_demo/docs/testing-guide.md
    title: login_demo 测试指南
  - id: session-rules
    resource: ../login_demo/docs/session-rules.md
    title: 登录会话有效期规则
---

# 测试路径

| 项目 | 值 |
|------|----|
| 测试文件 | `login_demo/tests/auth/test_session.py` |
| 测试说明 | `login_demo/docs/testing-guide.md` |
| 规则来源 | `login_demo/docs/session-rules.md` |

# 运行命令

统一入口（在 `login_demo/` 目录下运行）:[^testing-guide]

```bash
source .venv/bin/activate
python -m pytest tests/auth/test_session.py -q
```

- 不要直接敲 `pytest ...`，项目的 CI 只认 `python -m pytest` 形式。[^testing-guide]
- 运行前先激活虚拟环境：`source .venv/bin/activate`。[^testing-guide]
- 测试文件已移到 `tests/auth/` 子目录，命令路径相应为 `tests/auth/test_session.py`。[^test-file]
- `docs/testing-guide.md` 与测试文件头部注释仍写旧路径 `tests/test_session.py`，尚未同步更新。[^testing-guide][^test-file]

# 关键用例

测试文件按职责分为五个测试类：[^test-file]

- `TestSessionRules`：会话有效期规则，含 `test_expire_boundary`（`now == expires_at` 判为过期，返回 `False`）[^session-rules] 与 `test_refresh_extends_ttl`（续期推后 30 分钟）[^session-rules]。
- `TestVerifyToken`：令牌签名校验，伪造、篡改、畸形令牌均判无效。
- `TestIssueAndCheck`：签发后校验，覆盖到期边界（`test_invalid_at_expiry_boundary`）。
- `TestTouch`：续期从请求时刻起算，过期会话不可续期。
- `TestPurgeExpired`：只清理已过期记录。

> 旧记忆中的 `test_logout_invalidates` 已不在测试文件中：`app/auth.py` 的 `logout()` 仍是 `NotImplementedError`（TODO），退出登录尚未实现。[^test-file]

[^test-file]: login_demo 会话单元测试文件
[^testing-guide]: login_demo 测试指南
[^session-rules]: 登录会话有效期规则
