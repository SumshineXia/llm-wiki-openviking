# 配置 fail-closed 与通用 source bundle ingest 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复两个生产 bug：profile 定位失败后错误 fallback localhost；wiki-ingest 不能处理 OpenViking 上传后的多层 source bundle 目录。

**Architecture:** 分两个 PR 交付。PR 1 修改共享脚本 common.py/ovfs.py 实现配置层 fail-closed，统一 profile 选择逻辑，修复所有 CLI 脚本的错误处理。PR 2 重构 wiki-ingest 的 source 解析为通用 source bundle，支持任意后缀的目录递归发现。

**Tech Stack:** Python 3.9+, pytest, requests, OpenAI API

---

## File Structure

### PR 1 涉及文件

| 文件 | 操作 | 职责 |
|------|------|------|
| `skills/wiki-ingest/scripts/common.py` | 重写 | ConfigError + 配置解析 fail-closed + 共享 profile 函数 |
| `skills/wiki-ingest/scripts/ovfs.py` | 修改 | 移除 localhost fallback |
| 9 个 `skills/wiki-*/scripts/common.py` | 同步 | 与 wiki-ingest 版本保持一致 |
| 9 个 `skills/wiki-*/scripts/ovfs.py` | 同步 | 与 wiki-ingest 版本保持一致 |
| `skills/wiki-profile/scripts/profile.py` | 重写 | 复用 common.py 共享函数 |
| `skills/wiki-upload-source/scripts/upload.py` | 修改 | 入口返回码 + JSON 错误 |
| `skills/wiki-bootstrap/scripts/bootstrap.py` | 修改 | 入口返回码 + JSON 错误 |
| `skills/wiki-health/scripts/health.py` | 修改 | config 加载移入 try |
| `skills/wiki-lint/scripts/lint.py` | 修改 | config 加载移入 try |
| `skills/wiki-graph/scripts/graph.py` | 修改 | config 加载移入 try |
| `skills/wiki-query/scripts/query.py` | 修改 | config 加载移入 try |
| `skills/wiki-save/scripts/save.py` | 修改 | 错误输出增加 error_type |
| `skills/wiki-ingest/scripts/ingest.py` | 修改 | config 加载移入 try |
| `tests/skills/test_common_load_config.py` | 重写 | fail-closed 测试 |
| `tests/skills/test_ovfs_config_load.py` | 修改 | fail-closed 测试 |
| `tests/skills/test_profile_cli.py` | 修改 | 多 profile 报错 + fail helper |

### PR 2 涉及文件

| 文件 | 操作 | 职责 |
|------|------|------|
| `skills/wiki-ingest/scripts/ingest.py` | 修改 | source bundle 全套新函数 + main() 改造 |
| `skills/wiki-upload-source/scripts/upload.py` | 修改 | 返回 suggested_ingest_uri |
| `skills/wiki-ingest/SKILL.md` | 修改 | 文档更新 |
| `skills/wiki-upload-source/SKILL.md` | 修改 | 文档更新 |
| `tests/skills/test_ingest_source_bundle.py` | 新建 | source bundle 单元测试 |
| `tests/skills/test_ingest_chunking.py` | 修改 | FakeOVFSClient 扩展 |

---

## 基线

```bash
pytest tests/skills --tb=no -q
# 期望: 171 passed, 1 warning
```

---

# PR 1：配置/profile 层修复

## Task 1: 重写 common.py

**Files:**
- Modify: `skills/wiki-ingest/scripts/common.py` (完全重写)

- [ ] **Step 1: 写出完整的新 common.py**

```python
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


DEFAULT_CONFIG_PATH = Path.home() / ".config" / "llm-wiki-openviking" / "config.json"
DEFAULT_CURRENT_PROFILE_PATH = Path.home() / ".config" / "llm-wiki-openviking" / "current"


class ConfigError(ValueError):
    pass


def validate_kb_name(kbName: str) -> str:
    normalized = kbName.strip()
    if not normalized:
        raise ValueError("--kb-name 不能为空")
    if ".." in normalized or "//" in normalized:
        raise ValueError("--kb-name 不能包含 .. 或 //")
    if normalized.startswith("/") or normalized.endswith("/"):
        raise ValueError("--kb-name 不能以 / 开头或结尾")
    return normalized


def build_kb_root(kbName: str) -> str:
    valid_name = validate_kb_name(kbName)
    return f"viking://resources/{valid_name}/"


def resolve_config_path(config_path: str | None = None) -> Path:
    if config_path:
        return Path(config_path).expanduser()
    return DEFAULT_CONFIG_PATH


def read_text_file(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip()


def find_profile_marker(start: Path | None = None) -> tuple[str, Path | None]:
    current = start or Path.cwd()
    while True:
        marker = current / ".llm-wiki-profile"
        marker_value = read_text_file(marker)
        if marker_value:
            return marker_value, marker
        if current.parent == current:
            return "", None
        current = current.parent


def list_profiles(raw: dict[str, Any]) -> list[str]:
    profiles = raw.get("profiles")
    if not isinstance(profiles, list):
        return []
    result: list[str] = []
    for item in profiles:
        if not isinstance(item, dict):
            continue
        name = str(item.get("profile", "")).strip()
        if name:
            result.append(name)
    return result


def select_profile_name(
    profile_name: str | None,
    profile_map: dict[str, dict[str, Any]],
    start_dir: Path | None = None,
) -> tuple[str, str]:
    if profile_name and profile_name.strip():
        return profile_name.strip(), "--profile"

    env_profile = os.getenv("LLM_WIKI_PROFILE", "").strip()
    if env_profile:
        return env_profile, "LLM_WIKI_PROFILE"

    marker_profile, _ = find_profile_marker(start_dir)
    if marker_profile:
        return marker_profile, ".llm-wiki-profile"

    current_profile = read_text_file(DEFAULT_CURRENT_PROFILE_PATH)
    if current_profile:
        return current_profile, "current"

    names = sorted(profile_map.keys())
    if len(names) == 1:
        return names[0], "single-profile"

    if len(names) > 1:
        raise ConfigError(
            "配置中存在多个 profile，请使用 --profile、wiki-profile use <name> 或 wiki-profile bind <name>；"
            f"available_profiles={names}"
        )

    raise ConfigError("配置中未找到任何 profile")


def get_profile_by_name(raw: dict[str, Any], name: str) -> dict[str, Any]:
    profiles = raw.get("profiles")
    if not isinstance(profiles, list):
        raise ConfigError("配置中缺少 profiles 列表")
    for item in profiles:
        if not isinstance(item, dict):
            continue
        if str(item.get("profile", "")).strip() == name:
            return item
    available = list_profiles(raw)
    raise ConfigError(
        f"profile 不存在: {name}; available_profiles={available}"
    )


def mask_secret(value: str) -> str:
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}{'*' * (len(value) - 8)}{value[-4:]}"


def load_raw_config(config_path: str | None = None) -> tuple[dict[str, Any], Path]:
    selected_path = resolve_config_path(config_path)
    if not selected_path.exists():
        raise ConfigError(f"配置文件不存在: {selected_path}")
    raw_text = read_text_file(selected_path)
    if not raw_text:
        raise ConfigError(f"配置文件为空: {selected_path}")
    try:
        raw_data = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"配置文件 JSON 非法: {selected_path}; {exc}") from exc
    if not isinstance(raw_data, dict):
        raise ConfigError(f"配置文件必须是 JSON 对象: {selected_path}")
    return raw_data, selected_path


def _build_profile_map(raw: dict[str, Any]) -> dict[str, dict[str, Any]]:
    profiles = raw.get("profiles", [])
    profile_map: dict[str, dict[str, Any]] = {}
    for item in profiles:
        if isinstance(item, dict):
            name = str(item.get("profile", "")).strip()
            if name:
                profile_map[name] = item
    return profile_map


def parse_openviking_timeout(value: Any, config_path: Path) -> float:
    try:
        return float(value if value is not None else 30)
    except (TypeError, ValueError) as exc:
        raise ConfigError(
            f"openviking_timeout 非法: {value}; config={config_path}"
        ) from exc


def _normalize_flat_config(flat: dict[str, Any], config_path: Path) -> dict[str, Any]:
    flat["openviking_timeout"] = parse_openviking_timeout(
        flat.get("openviking_timeout", 30), config_path
    )
    return flat


def _to_flat_config(
    raw: dict[str, Any],
    profile_name: str | None,
    config_path: Path,
    start_dir: Path | None = None,
) -> dict[str, Any]:
    is_v2 = raw.get("version") == 2 and isinstance(raw.get("profiles"), list)
    if not is_v2:
        url = str(raw.get("openviking_url") or "").strip()
        if not url:
            raise ConfigError(f"flat config 缺少 openviking_url; config={config_path}")
        return _normalize_flat_config(dict(raw), config_path)

    profile_map = _build_profile_map(raw)

    if not profile_map:
        raise ConfigError(f"v2 config 中 profiles 为空; config={config_path}")

    selected_profile_name, profile_source = select_profile_name(
        profile_name, profile_map, start_dir
    )

    if selected_profile_name not in profile_map:
        raise ConfigError(
            f"profile 不存在: {selected_profile_name}; "
            f"available_profiles={sorted(profile_map.keys())}; "
            f"config={config_path}"
        )

    selected_profile = profile_map[selected_profile_name]
    system = selected_profile.get("system") if isinstance(selected_profile.get("system"), dict) else {}
    openviking = selected_profile.get("openviking") if isinstance(selected_profile.get("openviking"), dict) else {}
    openai = selected_profile.get("openai") if isinstance(selected_profile.get("openai"), dict) else {}
    defaults = selected_profile.get("defaults") if isinstance(selected_profile.get("defaults"), dict) else {}

    openviking_url = str(openviking.get("url") or "").strip()
    if not openviking_url:
        raise ConfigError(
            f"profile {selected_profile_name} 缺少 openviking.url; config={config_path}"
        )

    return {
        "profile": selected_profile_name,
        "profile_source": profile_source,
        "config_path": str(config_path),
        "system_id": system.get("id", ""),
        "system_name": system.get("name", ""),
        "ipmp_system_num": system.get("ipmp_system_num", ""),
        "openviking_url": openviking_url,
        "openviking_api_key": openviking.get("api_key", ""),
        "openviking_account_id": openviking.get("account_id", ""),
        "openviking_user_id": openviking.get("user_id", ""),
        "openviking_timeout": parse_openviking_timeout(openviking.get("timeout", 30), config_path),
        "openai_base_url": openai.get("base_url", ""),
        "openai_api_key": openai.get("api_key", ""),
        "openai_model": openai.get("model", "gpt-4o-mini"),
        "default_kb_name": defaults.get("kb_name", ""),
    }


def load_config(
    config_path: str | None = None,
    profile: str | None = None,
    start_dir: Path | None = None,
) -> dict[str, Any]:
    selected_path = resolve_config_path(config_path)

    if not selected_path.exists():
        raise ConfigError(f"配置文件不存在: {selected_path}")

    raw_text = read_text_file(selected_path)
    if not raw_text:
        raise ConfigError(f"配置文件为空: {selected_path}")

    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"配置文件 JSON 非法: {selected_path}; {exc}") from exc

    if not isinstance(data, dict):
        raise ConfigError(f"配置文件必须是 JSON 对象: {selected_path}")

    return _to_flat_config(data, profile, selected_path, start_dir)


def normalize_viking_uri(kbName: str, pathOrUri: str) -> str:
    kb_root = build_kb_root(kbName)
    normalized_path = pathOrUri.strip()

    if normalized_path.startswith("viking://"):
        return normalized_path

    if not normalized_path:
        return kb_root

    rel_path = normalized_path.lstrip("/")
    return f"{kb_root}{rel_path}"


def print_json(obj: dict[str, Any], pretty: bool) -> None:
    if pretty:
        print(json.dumps(obj, ensure_ascii=False, indent=2))
        return
    print(json.dumps(obj, ensure_ascii=False))


def build_error_result(exc: Exception, **context: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "status": "error",
        "error_type": exc.__class__.__name__,
        "error": str(exc),
    }
    for k, v in context.items():
        if v not in (None, ""):
            payload[k] = v
    return payload
```

- [ ] **Step 2: 替换 `skills/wiki-ingest/scripts/common.py` 全部内容为上述代码**

- [ ] **Step 3: Commit**

```bash
git add skills/wiki-ingest/scripts/common.py
git commit -m "refactor(common): rewrite common.py with ConfigError and fail-closed config loading"
```

---

## Task 2: 修改 ovfs.py 移除 localhost fallback

**Files:**
- Modify: `skills/wiki-ingest/scripts/ovfs.py:41`

- [ ] **Step 1: 修改 OVFSConfig.load() 中的 URL 获取逻辑**

找到 `skills/wiki-ingest/scripts/ovfs.py` 第 41 行：

```python
        url = str(config.get("openviking_url", "http://localhost:1933"))
```

替换为：

```python
        url = str(config.get("openviking_url") or "").strip()
        if not url:
            raise OVFSError("OpenViking URL 未配置，请检查 config/profile")
```

- [ ] **Step 2: Commit**

```bash
git add skills/wiki-ingest/scripts/ovfs.py
git commit -m "fix(ovfs): remove localhost fallback, raise OVFSError when URL missing"
```

---

## Task 3: 同步 common.py 和 ovfs.py 到所有 9 个 skill

**Files:**
- Modify: `skills/wiki-bootstrap/scripts/common.py`
- Modify: `skills/wiki-bootstrap/scripts/ovfs.py`
- Modify: `skills/wiki-health/scripts/common.py`
- Modify: `skills/wiki-health/scripts/ovfs.py`
- Modify: `skills/wiki-query/scripts/common.py`
- Modify: `skills/wiki-query/scripts/ovfs.py`
- Modify: `skills/wiki-lint/scripts/common.py`
- Modify: `skills/wiki-lint/scripts/ovfs.py`
- Modify: `skills/wiki-graph/scripts/common.py`
- Modify: `skills/wiki-graph/scripts/ovfs.py`
- Modify: `skills/wiki-upload-source/scripts/common.py`
- Modify: `skills/wiki-upload-source/scripts/ovfs.py`
- Modify: `skills/wiki-profile/scripts/common.py`
- Modify: `skills/wiki-profile/scripts/ovfs.py`
- Modify: `skills/wiki-save/scripts/common.py`
- Modify: `skills/wiki-save/scripts/ovfs.py`

- [ ] **Step 1: 执行同步脚本**

```bash
python3 -c "
from pathlib import Path
skills = [
    'wiki-bootstrap', 'wiki-health', 'wiki-query', 'wiki-lint',
    'wiki-graph', 'wiki-upload-source', 'wiki-profile', 'wiki-save',
]
root = Path('skills')
src_common = root / 'wiki-ingest' / 'scripts' / 'common.py'
src_ovfs = root / 'wiki-ingest' / 'scripts' / 'ovfs.py'
common_text = src_common.read_text(encoding='utf-8')
ovfs_text = src_ovfs.read_text(encoding='utf-8')
for s in skills:
    (root / s / 'scripts' / 'common.py').write_text(common_text, encoding='utf-8')
    (root / s / 'scripts' / 'ovfs.py').write_text(ovfs_text, encoding='utf-8')
print('synced to 8 skills')
"
```

- [ ] **Step 2: 运行一致性测试**

```bash
pytest tests/skills/test_shared_script_consistency.py -v
```

期望：通过。

- [ ] **Step 3: Commit**

```bash
git add skills/
git commit -m "sync: propagate fail-closed common.py and ovfs.py to all 9 skills"
```

---

## Task 4: 重写 test_common_load_config.py

**Files:**
- Modify: `tests/skills/test_common_load_config.py` (完全重写)

- [ ] **Step 1: 写出完整的新测试文件**

```python
import json
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest


repo_root = Path(__file__).resolve().parents[2]
module_path = repo_root / "skills" / "wiki-health" / "scripts" / "common.py"
spec = spec_from_file_location("wiki_health_common", module_path)
if spec is None or spec.loader is None:
    raise RuntimeError("无法加载 skills/wiki-health/scripts/common.py")
module = module_from_spec(spec)
spec.loader.exec_module(module)
load_config = module.load_config
ConfigError = module.ConfigError


def _clear_env(monkeypatch, tmp_path) -> None:
    for key in [
        "OPENVIKING_URL", "OPENVIKING_API_KEY", "OPENVIKING_ACCOUNT_ID",
        "OPENVIKING_USER_ID", "OPENVIKING_TIMEOUT", "OPENAI_BASE_URL",
        "OPENAI_API_KEY", "OPENAI_MODEL", "LLM_WIKI_CONFIG", "LLM_WIKI_PROFILE",
    ]:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(module, "DEFAULT_CURRENT_PROFILE_PATH", tmp_path / "current")


def _write_v2_config(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "version": 2,
                "profiles": [
                    {
                        "profile": "p1",
                        "system": {"id": "s1", "name": "System 1", "ipmp_system_num": "IPMP-1"},
                        "openviking": {
                            "url": "http://p1-host:1933",
                            "api_key": "p1-key",
                            "account_id": "p1-account",
                            "user_id": "p1-user",
                            "timeout": 11,
                        },
                        "openai": {
                            "base_url": "https://p1-openai.local",
                            "api_key": "p1-openai-key",
                            "model": "p1-model",
                        },
                        "defaults": {"kb_name": "kb-p1"},
                    },
                    {
                        "profile": "p2",
                        "system": {"id": "s2", "name": "System 2", "ipmp_system_num": "IPMP-2"},
                        "openviking": {
                            "url": "http://p2-host:1933",
                            "api_key": "p2-key",
                            "account_id": "p2-account",
                            "user_id": "p2-user",
                            "timeout": 22,
                        },
                        "openai": {
                            "base_url": "https://p2-openai.local",
                            "api_key": "p2-openai-key",
                            "model": "p2-model",
                        },
                        "defaults": {"kb_name": "kb-p2"},
                    },
                ],
            }
        ),
        encoding="utf-8",
    )


def _write_single_profile_config(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "version": 2,
                "profiles": [
                    {
                        "profile": "only",
                        "openviking": {
                            "url": "http://only-host:1933",
                            "api_key": "only-key",
                            "timeout": 15,
                        },
                    },
                ],
            }
        ),
        encoding="utf-8",
    )


def test_load_config_missing_file_fails_closed(tmp_path: Path, monkeypatch) -> None:
    _clear_env(monkeypatch, tmp_path)
    missing_path = tmp_path / "missing.json"

    with pytest.raises(ConfigError, match="配置文件不存在"):
        load_config(str(missing_path))


def test_load_config_empty_file_fails_closed(tmp_path: Path, monkeypatch) -> None:
    _clear_env(monkeypatch, tmp_path)
    config_path = tmp_path / "config.json"
    config_path.write_text("", encoding="utf-8")

    with pytest.raises(ConfigError, match="配置文件为空"):
        load_config(str(config_path))


def test_load_config_invalid_json_fails_closed(tmp_path: Path, monkeypatch) -> None:
    _clear_env(monkeypatch, tmp_path)
    config_path = tmp_path / "config.json"
    config_path.write_text("{bad json", encoding="utf-8")

    with pytest.raises(ConfigError, match="JSON 非法"):
        load_config(str(config_path))


def test_load_config_non_object_json_fails_closed(tmp_path: Path, monkeypatch) -> None:
    _clear_env(monkeypatch, tmp_path)
    config_path = tmp_path / "config.json"
    config_path.write_text("[1, 2, 3]", encoding="utf-8")

    with pytest.raises(ConfigError, match="JSON 对象"):
        load_config(str(config_path))


def test_load_config_flat_config_requires_openviking_url(tmp_path: Path, monkeypatch) -> None:
    _clear_env(monkeypatch, tmp_path)
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"profile": "legacy", "openviking_api_key": "k"}),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="flat config 缺少 openviking_url"):
        load_config(str(config_path))


def test_load_config_flat_config_with_explicit_localhost_is_allowed(tmp_path: Path, monkeypatch) -> None:
    _clear_env(monkeypatch, tmp_path)
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({
            "openviking_url": "http://localhost:1933",
            "openviking_api_key": "file-key",
            "openviking_timeout": 12,
        }),
        encoding="utf-8",
    )

    config = load_config(str(config_path))

    assert config["openviking_url"] == "http://localhost:1933"
    assert config["openviking_timeout"] == 12


def test_load_config_uses_file_values_over_env(tmp_path: Path, monkeypatch) -> None:
    _clear_env(monkeypatch, tmp_path)
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({
            "openviking_url": "http://file-host:1933",
            "openviking_api_key": "file-key",
            "openviking_account_id": "file-account",
            "openviking_user_id": "file-user",
            "openviking_timeout": 12,
            "openai_base_url": "https://file-openai.local",
            "openai_api_key": "file-openai-key",
            "openai_model": "file-model",
            "default_kb_name": "file-kb",
        }),
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENVIKING_URL", "http://env-host:1933")
    monkeypatch.setenv("OPENVIKING_API_KEY", "env-key")

    config = load_config(str(config_path))

    assert config["openviking_url"] == "http://file-host:1933"
    assert config["openviking_api_key"] == "file-key"
    assert isinstance(config["openviking_timeout"], float)


def test_load_config_ignores_openviking_env_overrides(tmp_path: Path, monkeypatch) -> None:
    _clear_env(monkeypatch, tmp_path)
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"openviking_url": "http://file-host:1933", "openviking_timeout": 12}),
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENVIKING_URL", "http://env-host:1933")
    monkeypatch.setenv("OPENVIKING_TIMEOUT", "99")

    config = load_config(str(config_path))

    assert config["openviking_url"] == "http://file-host:1933"
    assert config["openviking_timeout"] == 12.0


def test_load_config_explicit_config_path_overrides_llm_wiki_config(
    tmp_path: Path, monkeypatch,
) -> None:
    _clear_env(monkeypatch, tmp_path)
    explicit_config_path = tmp_path / "explicit-config.json"
    explicit_config_path.write_text(
        json.dumps({
            "openviking_url": "http://explicit-host:1933",
            "openviking_api_key": "explicit-key",
        }),
        encoding="utf-8",
    )
    monkeypatch.setenv("LLM_WIKI_CONFIG", "/nonexistent/path.json")

    config = load_config(str(explicit_config_path))

    assert config["openviking_url"] == "http://explicit-host:1933"
    assert config["openviking_api_key"] == "explicit-key"


def test_load_config_llm_wiki_config_env_is_ignored(tmp_path: Path, monkeypatch) -> None:
    _clear_env(monkeypatch, tmp_path)
    monkeypatch.setattr(module, "DEFAULT_CONFIG_PATH", tmp_path / "default-config.json")
    env_config_path = tmp_path / "env-config.json"
    _write_v2_config(env_config_path)
    monkeypatch.setenv("LLM_WIKI_CONFIG", str(env_config_path))

    with pytest.raises(ConfigError, match="配置文件不存在"):
        load_config()


def test_load_config_explicit_profile_has_highest_priority(tmp_path: Path, monkeypatch) -> None:
    _clear_env(monkeypatch, tmp_path)
    config_path = tmp_path / "config.json"
    _write_v2_config(config_path)
    monkeypatch.setenv("LLM_WIKI_PROFILE", "p1")

    config = load_config(str(config_path), profile="p2")

    assert config["profile"] == "p2"
    assert config["openviking_url"] == "http://p2-host:1933"
    assert config["profile_source"] == "--profile"


def test_load_config_env_profile_selects_profile(tmp_path: Path, monkeypatch) -> None:
    _clear_env(monkeypatch, tmp_path)
    config_path = tmp_path / "config.json"
    _write_v2_config(config_path)
    monkeypatch.setenv("LLM_WIKI_PROFILE", "p2")

    config = load_config(str(config_path))

    assert config["profile"] == "p2"
    assert config["profile_source"] == "LLM_WIKI_PROFILE"


def test_load_config_invalid_env_profile_fails_closed(tmp_path: Path, monkeypatch) -> None:
    _clear_env(monkeypatch, tmp_path)
    config_path = tmp_path / "config.json"
    _write_v2_config(config_path)
    monkeypatch.setenv("LLM_WIKI_PROFILE", "missing-profile")

    with pytest.raises(ConfigError, match="profile 不存在.*missing-profile"):
        load_config(str(config_path))


def test_load_config_invalid_explicit_profile_fails_closed(tmp_path: Path, monkeypatch) -> None:
    _clear_env(monkeypatch, tmp_path)
    config_path = tmp_path / "config.json"
    _write_v2_config(config_path)

    with pytest.raises(ConfigError, match="profile 不存在.*nonexistent"):
        load_config(str(config_path), profile="nonexistent")


def test_load_config_uses_single_profile_by_default(tmp_path: Path, monkeypatch) -> None:
    _clear_env(monkeypatch, tmp_path)
    config_path = tmp_path / "config.json"
    _write_single_profile_config(config_path)

    config = load_config(str(config_path))

    assert config["profile"] == "only"
    assert config["profile_source"] == "single-profile"
    assert config["openviking_url"] == "http://only-host:1933"


def test_load_config_rejects_ambiguous_multiple_profiles_without_selection(
    tmp_path: Path, monkeypatch,
) -> None:
    _clear_env(monkeypatch, tmp_path)
    config_path = tmp_path / "config.json"
    _write_v2_config(config_path)

    with pytest.raises(ConfigError, match="多个 profile"):
        load_config(str(config_path))


def test_load_config_current_file_selects_profile(tmp_path: Path, monkeypatch) -> None:
    _clear_env(monkeypatch, tmp_path)
    config_path = tmp_path / "config.json"
    _write_v2_config(config_path)
    current_path = tmp_path / "current"
    current_path.write_text("p2\n", encoding="utf-8")
    monkeypatch.setattr(module, "DEFAULT_CURRENT_PROFILE_PATH", current_path)

    config = load_config(str(config_path))

    assert config["profile"] == "p2"
    assert config["profile_source"] == "current"


def test_load_config_profile_source_includes_config_path(tmp_path: Path, monkeypatch) -> None:
    _clear_env(monkeypatch, tmp_path)
    config_path = tmp_path / "config.json"
    _write_single_profile_config(config_path)

    config = load_config(str(config_path))

    assert "config_path" in config
    assert config["config_path"] == str(config_path)


def test_load_config_timeout_cast_to_float(tmp_path: Path, monkeypatch) -> None:
    _clear_env(monkeypatch, tmp_path)
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"openviking_url": "http://h:1933", "openviking_timeout": 22}), encoding="utf-8")

    config = load_config(str(config_path))

    assert config["openviking_timeout"] == 22.0
    assert isinstance(config["openviking_timeout"], float)
```

- [ ] **Step 2: 替换 `tests/skills/test_common_load_config.py` 全部内容为上述代码**

- [ ] **Step 3: 运行测试验证**

```bash
pytest tests/skills/test_common_load_config.py -v
```

期望：全部通过。

- [ ] **Step 4: Commit**

```bash
git add tests/skills/test_common_load_config.py
git commit -m "test(common): rewrite fail-closed config loading tests"
```

---

## Task 5: 重写 test_ovfs_config_load.py

**Files:**
- Modify: `tests/skills/test_ovfs_config_load.py`

- [ ] **Step 1: 写出完整的新测试文件**

```python
import json
import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest


repoRoot = Path(__file__).resolve().parents[2]
scriptsDir = repoRoot / "skills" / "wiki-health" / "scripts"
ovfsPath = scriptsDir / "ovfs.py"
if str(scriptsDir) not in sys.path:
    sys.path.insert(0, str(scriptsDir))
import common as common_module

spec = spec_from_file_location("wiki_health_ovfs", ovfsPath)
if spec is None or spec.loader is None:
    raise RuntimeError("无法加载 skills/wiki-health/scripts/ovfs.py")
module = module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
OVFSConfig = module.OVFSConfig
OVFSClient = module.OVFSClient
OVFSError = module.OVFSError
ConfigError = common_module.ConfigError


def _clear_env(monkeypatch) -> None:
    for key in [
        "OPENVIKING_URL", "OPENVIKING_API_KEY", "OPENVIKING_ACCOUNT_ID",
        "OPENVIKING_USER_ID", "OPENVIKING_TIMEOUT", "LLM_WIKI_CONFIG",
        "LLM_WIKI_PROFILE",
    ]:
        monkeypatch.delenv(key, raising=False)


def test_load_missing_config_fails_closed(tmp_path: Path, monkeypatch) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setattr(common_module, "DEFAULT_CONFIG_PATH", tmp_path / "missing.json")

    with pytest.raises(ConfigError, match="配置文件不存在"):
        OVFSConfig.load()


def test_load_ignores_env_overrides(tmp_path: Path, monkeypatch) -> None:
    _clear_env(monkeypatch)
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"openviking_url": "http://file-host:1933", "openviking_api_key": "file-key"}),
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENVIKING_URL", "http://env-host:1933")
    monkeypatch.setenv("OPENVIKING_API_KEY", "env-key")

    config = OVFSConfig.load(config_path=str(config_path))

    assert config.url == "http://file-host:1933"
    assert config.api_key == "file-key"


def test_load_reads_profile_from_v2_config(tmp_path: Path, monkeypatch) -> None:
    _clear_env(monkeypatch)
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({
            "version": 2,
            "profiles": [{
                "profile": "dev",
                "system": {"name": "Dev System"},
                "openviking": {
                    "url": "http://dev:1933",
                    "api_key": "dev-key",
                    "account_id": "dev-account",
                    "user_id": "dev-user",
                    "timeout": 18,
                },
            }],
        }),
        encoding="utf-8",
    )

    config = OVFSConfig.load(config_path=str(config_path), profile="dev")

    assert config.url == "http://dev:1933"
    assert config.api_key == "dev-key"
    assert config.account_id == "dev-account"
    assert config.user_id == "dev-user"
    assert config.profile == "dev"
    assert config.system_name == "Dev System"
    assert config.timeout == 18.0


def test_load_invalid_profile_fails_closed(tmp_path: Path, monkeypatch) -> None:
    _clear_env(monkeypatch)
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({
            "version": 2,
            "profiles": [{"profile": "dev", "openviking": {"url": "http://dev:1933"}}],
        }),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="profile 不存在.*wrong"):
        OVFSConfig.load(config_path=str(config_path), profile="wrong")


def test_load_empty_url_in_config_raises_config_error(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"openviking_url": "", "openviking_api_key": "k"}),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="flat config 缺少 openviking_url"):
        OVFSConfig.load(config_path=str(config_path))


def test_load_missing_url_in_config_raises_config_error(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"openviking_api_key": "k"}),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="flat config 缺少 openviking_url"):
        OVFSConfig.load(config_path=str(config_path))


def test_ovfs_config_raises_ovfs_error_when_load_config_returns_empty_url(
    tmp_path: Path, monkeypatch,
) -> None:
    monkeypatch.setattr(module, "load_config", lambda **kw: {"openviking_url": ""})

    with pytest.raises(OVFSError, match="OpenViking URL 未配置"):
        OVFSConfig.load(config_path=str(tmp_path / "x.json"))


def test_client_sets_auth_headers() -> None:
    config = OVFSConfig(
        url="http://localhost:1933",
        api_key="header-key",
        account_id="header-account",
        user_id="header-user",
    )

    client = OVFSClient(config=config)
    try:
        assert client.session.headers.get("X-API-Key") == "header-key"
        assert client.session.headers.get("X-OpenViking-Account") == "header-account"
        assert client.session.headers.get("X-OpenViking-User") == "header-user"
    finally:
        client.close()
```

- [ ] **Step 2: 替换 `tests/skills/test_ovfs_config_load.py` 全部内容为上述代码**

- [ ] **Step 3: 运行测试验证**

```bash
pytest tests/skills/test_ovfs_config_load.py -v
```

期望：全部通过。

- [ ] **Step 4: Commit**

```bash
git add tests/skills/test_ovfs_config_load.py
git commit -m "test(ovfs): rewrite config loading tests with fail-closed expectations"
```

---

## Task 6: 重写 profile.py

**Files:**
- Modify: `skills/wiki-profile/scripts/profile.py` (完全重写)

- [ ] **Step 1: 写出完整的新 profile.py**

```python
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from common import (
    ConfigError,
    build_error_result,
    find_profile_marker,
    get_profile_by_name,
    list_profiles,
    load_raw_config,
    mask_secret,
    print_json,
    read_text_file,
    resolve_config_path,
    select_profile_name,
)


def _build_profile_map(raw: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in raw.get("profiles", []):
        if isinstance(item, dict):
            name = str(item.get("profile", "")).strip()
            if name:
                result[name] = item
    return result


def _validate_profile_usable(raw: dict[str, Any], name: str) -> dict[str, Any]:
    profile = get_profile_by_name(raw, name)
    openviking = profile.get("openviking") if isinstance(profile.get("openviking"), dict) else {}
    if not str(openviking.get("url") or "").strip():
        raise ConfigError(f"profile {name} 缺少 openviking.url，不能 use/bind")
    return profile


def _write_current_profile(profile_name: str) -> Path:
    from common import DEFAULT_CURRENT_PROFILE_PATH
    DEFAULT_CURRENT_PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEFAULT_CURRENT_PROFILE_PATH.write_text(profile_name + "\n", encoding="utf-8")
    return DEFAULT_CURRENT_PROFILE_PATH


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="管理 llm-wiki-openviking 的 profile 选择")
    parser.add_argument("--config", default=None, help="配置文件路径，默认读取 ~/.config/llm-wiki-openviking/config.json")
    parser.add_argument("--profile", default=None, help="显式指定 profile 名称（仅影响本次命令）")
    parser.add_argument("--pretty", action="store_true", help="格式化输出 JSON")

    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("list", help="列出所有 profile")
    subparsers.add_parser("current", help="显示当前生效 profile 及来源")

    use_parser = subparsers.add_parser("use", help="将某个 profile 设为 current")
    use_parser.add_argument("name", help="profile 名称")

    show_parser = subparsers.add_parser("show", help="显示指定 profile 的详细信息")
    show_parser.add_argument("name", nargs="?", default=None, help="profile 名称，缺省则显示当前生效 profile")

    bind_parser = subparsers.add_parser("bind", help="在目录写入 .llm-wiki-profile")
    bind_parser.add_argument("name", help="profile 名称")
    bind_parser.add_argument("--dir", default=".", help="绑定目录，默认当前目录")

    unbind_parser = subparsers.add_parser("unbind", help="删除目录中的 .llm-wiki-profile")
    unbind_parser.add_argument("--dir", default=".", help="解绑目录，默认当前目录")

    return parser.parse_args()


def main() -> int:
    args = parse_args()

    try:
        raw, config_file_path = load_raw_config(args.config)
        config_path_str = str(config_file_path)

        if args.command == "list":
            names = list_profiles(raw)
            print_json({"status": "ok", "config_path": config_path_str, "profiles": names}, args.pretty)
            return 0

        if args.command == "current":
            profile_map = _build_profile_map(raw)
            profile_name, source = select_profile_name(args.profile, profile_map)
            get_profile_by_name(raw, profile_name)
            print_json(
                {"status": "ok", "config_path": config_path_str, "profile": profile_name, "source": source},
                args.pretty,
            )
            return 0

        if args.command == "use":
            _validate_profile_usable(raw, args.name)
            current_path = _write_current_profile(args.name)
            print_json(
                {"status": "ok", "config_path": config_path_str, "profile": args.name, "current_path": str(current_path)},
                args.pretty,
            )
            return 0

        if args.command == "show":
            if args.name:
                target_name = args.name
                profile_source = "argument"
            else:
                profile_map = _build_profile_map(raw)
                target_name, profile_source = select_profile_name(args.profile, profile_map)
            profile = get_profile_by_name(raw, target_name)

            openai = profile.get("openai") if isinstance(profile.get("openai"), dict) else {}
            openviking = profile.get("openviking") if isinstance(profile.get("openviking"), dict) else {}

            masked_openai = dict(openai)
            if isinstance(masked_openai.get("api_key"), str):
                masked_openai["api_key"] = mask_secret(masked_openai["api_key"])
            masked_openviking = dict(openviking)
            if isinstance(masked_openviking.get("api_key"), str):
                masked_openviking["api_key"] = mask_secret(masked_openviking["api_key"])

            masked_profile = dict(profile)
            masked_profile["openai"] = masked_openai
            masked_profile["openviking"] = masked_openviking

            openviking_url = ""
            if isinstance(openviking, dict) and isinstance(openviking.get("url"), str):
                openviking_url = openviking["url"]

            print_json(
                {
                    "status": "ok",
                    "config_path": config_path_str,
                    "profile": target_name,
                    "profile_source": profile_source,
                    "openviking_url": openviking_url,
                    "data": masked_profile,
                },
                args.pretty,
            )
            return 0

        if args.command == "bind":
            _validate_profile_usable(raw, args.name)
            bind_dir = Path(args.dir).expanduser().resolve()
            bind_dir.mkdir(parents=True, exist_ok=True)
            marker_path = bind_dir / ".llm-wiki-profile"
            marker_path.write_text(args.name + "\n", encoding="utf-8")
            print_json({"status": "ok", "profile": args.name, "marker": str(marker_path)}, args.pretty)
            return 0

        if args.command == "unbind":
            bind_dir = Path(args.dir).expanduser().resolve()
            marker_path = bind_dir / ".llm-wiki-profile"
            removed = False
            if marker_path.exists():
                marker_path.unlink()
                removed = True
            print_json({"status": "ok", "marker": str(marker_path), "removed": removed}, args.pretty)
            return 0

        raise ValueError(f"不支持的命令: {args.command}")

    except Exception as exc:
        print_json(build_error_result(exc), args.pretty)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: 替换 `skills/wiki-profile/scripts/profile.py` 全部内容为上述代码**

- [ ] **Step 3: Commit**

```bash
git add skills/wiki-profile/scripts/profile.py
git commit -m "refactor(profile): reuse common.py shared functions for profile selection"
```

---

## Task 7: 更新 test_profile_cli.py

**Files:**
- Modify: `tests/skills/test_profile_cli.py`

- [ ] **Step 1: 写出完整的新测试文件**

```python
import json
import os
from pathlib import Path
import subprocess

import pytest


repo_root = Path(__file__).resolve().parents[2]
profile_script = repo_root / "skills" / "wiki-profile" / "scripts" / "profile.py"


def _write_config(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "version": 2,
                "profiles": [
                    {
                        "profile": "p1",
                        "openviking": {"url": "http://p1:1933", "api_key": "12345678"},
                        "openai": {"api_key": "abcd1234efgh5678"},
                    },
                    {
                        "profile": "p2",
                        "openviking": {"url": "http://p2:1933", "api_key": "p2-openviking-key"},
                        "openai": {"api_key": "p2-openai-key"},
                    },
                ],
            }
        ),
        encoding="utf-8",
    )


def _run(args: list[str], cwd: Path, env: dict[str, str]) -> dict:
    process = subprocess.run(
        ["python3", str(profile_script), *args],
        check=True,
        capture_output=True,
        text=True,
        cwd=str(cwd),
        env=env,
    )
    return json.loads(process.stdout)


def _run_allow_fail(args: list[str], cwd: Path, env: dict[str, str]) -> tuple[int, dict]:
    process = subprocess.run(
        ["python3", str(profile_script), *args],
        check=False,
        capture_output=True,
        text=True,
        cwd=str(cwd),
        env=env,
    )
    payload = json.loads(process.stdout) if process.stdout.strip() else {}
    return process.returncode, payload


def _make_env(tmp_path: Path, **overrides: str) -> dict[str, str]:
    config_home = tmp_path / "home"
    config_home.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["HOME"] = str(config_home)
    env.pop("LLM_WIKI_PROFILE", None)
    env.pop("OPENVIKING_URL", None)
    env.pop("OPENVIKING_API_KEY", None)
    env.update(overrides)
    return env


def test_profile_list(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "config.json"
    _write_config(config_path)
    env = _make_env(tmp_path)

    result = _run(["--config", str(config_path), "list"], tmp_path, env)
    assert result["status"] == "ok"
    assert result["profiles"] == ["p1", "p2"]


def test_profile_current_multiple_profiles_without_selection_errors(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    _write_config(config_path)
    env = _make_env(tmp_path)

    exit_code, payload = _run_allow_fail(["--config", str(config_path), "current"], tmp_path, env)

    assert exit_code == 1
    assert payload["status"] == "error"
    assert "ConfigError" in payload.get("error_type", "")
    assert "多个 profile" in payload.get("error", "")


def test_profile_current_with_cli_profile(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    _write_config(config_path)
    env = _make_env(tmp_path)

    result = _run(["--config", str(config_path), "--profile", "p2", "current"], tmp_path, env)
    assert result["profile"] == "p2"
    assert result["source"] == "--profile"


def test_profile_current_with_env_profile(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    _write_config(config_path)
    env = _make_env(tmp_path, LLM_WIKI_PROFILE="p2")

    result = _run(["--config", str(config_path), "current"], tmp_path, env)
    assert result["profile"] == "p2"
    assert result["source"] == "LLM_WIKI_PROFILE"


def test_profile_current_with_marker(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    _write_config(config_path)
    env = _make_env(tmp_path)
    work_dir = tmp_path / "workspace" / "a" / "b"
    work_dir.mkdir(parents=True, exist_ok=True)
    (tmp_path / "workspace" / ".llm-wiki-profile").write_text("p2\n", encoding="utf-8")

    result = _run(["--config", str(config_path), "current"], work_dir, env)
    assert result["profile"] == "p2"
    assert result["source"] == ".llm-wiki-profile"


def test_profile_use_and_current_file(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    _write_config(config_path)
    env = _make_env(tmp_path)

    used = _run(["--config", str(config_path), "use", "p2"], tmp_path, env)
    assert used["profile"] == "p2"

    current = _run(["--config", str(config_path), "current"], tmp_path, env)
    assert current["profile"] == "p2"
    assert current["source"] == "current"


def test_profile_show_masks_api_keys(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    _write_config(config_path)
    env = _make_env(tmp_path, LLM_WIKI_PROFILE="p1")

    shown = _run(["--config", str(config_path), "show", "p1"], tmp_path, env)
    assert shown["profile"] == "p1"
    assert shown["profile_source"] == "argument"
    assert shown["openviking_url"] == "http://p1:1933"
    assert shown["data"]["openviking"]["api_key"] == "********"
    assert shown["data"]["openai"]["api_key"] == "abcd********5678"


def test_profile_bind_and_unbind(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    _write_config(config_path)
    env = _make_env(tmp_path)

    bind_dir = tmp_path / "bind-dir"
    bound = _run(["--config", str(config_path), "bind", "p1", "--dir", str(bind_dir)], tmp_path, env)
    assert Path(bound["marker"]).exists()

    unbound = _run(["--config", str(config_path), "unbind", "--dir", str(bind_dir)], tmp_path, env)
    assert unbound["removed"] is True
    assert not (bind_dir / ".llm-wiki-profile").exists()
```

- [ ] **Step 2: 替换 `tests/skills/test_profile_cli.py` 全部内容为上述代码**

- [ ] **Step 3: 运行测试验证**

```bash
pytest tests/skills/test_profile_cli.py -v
```

期望：全部通过。

- [ ] **Step 4: Commit**

```bash
git add tests/skills/test_profile_cli.py
git commit -m "test(profile): update profile CLI tests for fail-closed behavior"
```

---

## Task 8: 修复所有 CLI 脚本的错误处理和入口返回码

**Files:**
- Modify: `skills/wiki-upload-source/scripts/upload.py:73-87`
- Modify: `skills/wiki-bootstrap/scripts/bootstrap.py:70-90`
- Modify: `skills/wiki-health/scripts/health.py:521-559`
- Modify: `skills/wiki-lint/scripts/lint.py:590-628`
- Modify: `skills/wiki-graph/scripts/graph.py:888-940`
- Modify: `skills/wiki-query/scripts/query.py:950-1125`
- Modify: `skills/wiki-save/scripts/save.py:398-400`
- Modify: `skills/wiki-ingest/scripts/ingest.py:962-1163`

- [ ] **Step 1: 修改 upload.py — 添加 try/except + 入口返回码**

找到 `skills/wiki-upload-source/scripts/upload.py` 中的：

```python
from common import build_kb_root, normalize_viking_uri, print_json, validate_kb_name
```

替换为：

```python
from common import build_error_result, build_kb_root, normalize_viking_uri, print_json, validate_kb_name
```

找到：

```python
def main() -> None:
  args = parse_args()
  result = runUpload(
    args.kb_name,
    args.file,
    args.to,
    waitForCompletion=args.wait,
    configPath=args.config,
    profile=args.profile,
  )
  print_json(result, pretty=args.pretty)


if __name__ == "__main__":
  main()
```

替换为：

```python
def main() -> int:
  args = parse_args()
  try:
    result = runUpload(
      args.kb_name,
      args.file,
      args.to,
      waitForCompletion=args.wait,
      configPath=args.config,
      profile=args.profile,
    )
    print_json(result, pretty=args.pretty)
    return 0
  except Exception as exc:
    print_json(build_error_result(exc), pretty=args.pretty)
    return 1


if __name__ == "__main__":
  raise SystemExit(main())
```

- [ ] **Step 2: 修改 bootstrap.py — 添加 try/except + 入口返回码**

找到 `skills/wiki-bootstrap/scripts/bootstrap.py` 中的：

```python
from common import build_kb_root, print_json, validate_kb_name
```

替换为：

```python
from common import build_error_result, build_kb_root, print_json, validate_kb_name
```

找到：

```python
def main() -> None:
  args = parse_args()
  plan = plan_bootstrap_paths(args.kb_name)
  config = OVFSConfig.load(config_path=args.config, profile=args.profile)
  result: dict[str, Any] = {
    "kb_name": validate_kb_name(args.kb_name),
    "dry_run": bool(args.dry_run),
    "plan": plan,
  }

  if args.dry_run:
    print_json(result, args.pretty)
    return

  apply_bootstrap(plan, config)
  result["status"] = "ok"
  print_json(result, args.pretty)


if __name__ == "__main__":
  main()
```

替换为：

```python
def main() -> int:
  args = parse_args()
  try:
    plan = plan_bootstrap_paths(args.kb_name)
    config = OVFSConfig.load(config_path=args.config, profile=args.profile)
    result: dict[str, Any] = {
      "kb_name": validate_kb_name(args.kb_name),
      "dry_run": bool(args.dry_run),
      "plan": plan,
    }

    if args.dry_run:
      print_json(result, args.pretty)
      return 0

    apply_bootstrap(plan, config)
    result["status"] = "ok"
    print_json(result, args.pretty)
    return 0
  except Exception as exc:
    print_json(build_error_result(exc), args.pretty)
    return 1


if __name__ == "__main__":
  raise SystemExit(main())
```

- [ ] **Step 3: 修改 health.py — config 加载移入 try**

找到 `skills/wiki-health/scripts/health.py` 中的：

```python
def main() -> int:
  args = parse_args()
  kbRoot = build_kb_root(args.kb_name)
  config = OVFSConfig.load(config_path=args.config, profile=args.profile)

  try:
```

替换为：

```python
def main() -> int:
  args = parse_args()
  kbRoot = ""

  try:
    kbRoot = build_kb_root(args.kb_name)
    config = OVFSConfig.load(config_path=args.config, profile=args.profile)
```

同时，找到 health.py 的错误处理块：

```python
  except OVFSError as exc:
    errorReport = {
      "status": "error",
      "kb_root": kbRoot,
      "errors": [f"OVFS 错误：{str(exc)}"],
      "warnings": [],
      "details": {},
    }
    print(json.dumps(errorReport, ensure_ascii=False, indent=2))
    return 2
  except Exception as exc:
    errorReport = {
      "status": "error",
      "kb_root": kbRoot,
      "errors": [f"未预期错误：{str(exc)}"],
      "warnings": [],
      "details": {},
    }
    print(json.dumps(errorReport, ensure_ascii=False, indent=2))
    return 3
```

替换为：

```python
  except Exception as exc:
    from common import build_error_result, print_json
    print_json(build_error_result(exc, kb_root=kbRoot), args.pretty)
    return 1
```

注意：`print_json` 和 `args.pretty` 需要在作用域内。`print_json` 来自 common import，`args` 来自 parse_args()。确认 health.py 的 import 行中已有 `from common import ... print_json ...`。如果已有 `import json` 的 `print(json.dumps(...))` 写法，需要改为使用 `print_json`。

具体做法：在 health.py 顶部 import 中确保有 `print_json`，然后替换整个 except 块。

- [ ] **Step 4: 修改 lint.py — config 加载移入 try**

与 health.py 相同模式。找到 `skills/wiki-lint/scripts/lint.py` 中的：

```python
def main() -> int:
    args = parse_args()
    kb_root = build_kb_root(args.kb_name)
    config = OVFSConfig.load(config_path=args.config, profile=args.profile)

    try:
```

替换为：

```python
def main() -> int:
    args = parse_args()
    kb_root = ""

    try:
        kb_root = build_kb_root(args.kb_name)
        config = OVFSConfig.load(config_path=args.config, profile=args.profile)
```

找到 lint.py 的错误处理块（与 health.py 结构相同），替换为：

```python
    except Exception as exc:
        from common import build_error_result, print_json
        print_json(build_error_result(exc, kb_root=kb_root), args.pretty)
        return 1
```

- [ ] **Step 5: 修改 graph.py — config 加载移入 try**

找到 `skills/wiki-graph/scripts/graph.py` 中的：

```python
def main() -> int:
    args = parse_args()
    kb_root = build_kb_root(args.kb_name)
    config = OVFSConfig.load(config_path=args.config, profile=args.profile)

    try:
```

替换为：

```python
def main() -> int:
    args = parse_args()
    kb_root = ""

    try:
        kb_root = build_kb_root(args.kb_name)
        config = OVFSConfig.load(config_path=args.config, profile=args.profile)
```

找到 graph.py 的错误处理块：

```python
    except Exception as exc:
        error_result = {
            "status": "error",
            "kb_root": kb_root,
            "error": str(exc),
        }
        print(json.dumps(error_result, ensure_ascii=False, indent=2))
        return 1
```

替换为：

```python
    except Exception as exc:
        from common import build_error_result, print_json
        print_json(build_error_result(exc, kb_root=kb_root), args.pretty)
        return 1
```

- [ ] **Step 6: 修改 query.py — config 加载移入 try**

找到 `skills/wiki-query/scripts/query.py` 中的：

```python
def main() -> int:
    args = parse_args()
    kb_root = build_kb_root(args.kb_name)
    schema_text = read_local_schema()
    config = OVFSConfig.load(config_path=args.config, profile=args.profile)
    openai_settings = resolve_openai_settings(args)

    try:
```

替换为：

```python
def main() -> int:
    args = parse_args()
    kb_root = ""

    try:
        kb_root = build_kb_root(args.kb_name)
        schema_text = read_local_schema()
        config = OVFSConfig.load(config_path=args.config, profile=args.profile)
        openai_settings = resolve_openai_settings(args)
```

找到 query.py 的错误处理块：

```python
    except Exception as exc:
        error_result = {
            "status": "error",
            "kb_root": kb_root,
            "question": args.question,
            "error": str(exc),
        }
        print(json.dumps(error_result, ensure_ascii=False, indent=2))
        return 1
```

替换为：

```python
    except Exception as exc:
        from common import build_error_result, print_json
        print_json(build_error_result(exc, kb_root=kb_root, question=args.question), args.pretty)
        return 1
```

- [ ] **Step 7: 修改 save.py — 错误输出增加 error_type**

找到 `skills/wiki-save/scripts/save.py` 中的：

```python
  except Exception as exc:
    print_json({"status": "error", "error": str(exc)}, pretty=True)
    return 1
```

替换为：

```python
  except Exception as exc:
    from common import build_error_result, print_json
    print_json(build_error_result(exc), pretty=True)
    return 1
```

- [ ] **Step 8: 修改 ingest.py — config 加载移入 try**

找到 `skills/wiki-ingest/scripts/ingest.py` 中的：

```python
def main() -> int:
    args = parse_args()
    kb_root = build_kb_root(args.kb_name)
    schema_text = read_local_schema()
    _ = load_config(config_path=args.config, profile=args.profile)
    config = OVFSConfig.load(config_path=args.config, profile=args.profile)
    openai_settings = resolve_openai_settings(args)

    try:
        with OVFSClient(config) as client:
```

替换为：

```python
def main() -> int:
    args = parse_args()
    kb_root = ""

    try:
        kb_root = build_kb_root(args.kb_name)
        schema_text = read_local_schema()
        config = OVFSConfig.load(config_path=args.config, profile=args.profile)
        openai_settings = resolve_openai_settings(args)

        with OVFSClient(config) as client:
```

同时，在 ingest.py 的 import 行中添加 `print_json`（错误输出需要）：

找到：

```python
from common import build_kb_root
```

替换为：

```python
from common import build_error_result, build_kb_root, load_config, print_json
```

注意：保留 `load_config` import，因为 `resolve_openai_settings()` 仍然调用它。本次不修改 `resolve_openai_settings()` 签名，接受重复调用。后续优化可传入 `runtime_config` 参数消除重复。

- [ ] **Step 9: 运行测试验证受影响的脚本测试**

```bash
pytest tests/skills/ -v --tb=short
```

期望：全部通过。如果有 test_health / test_lint / test_graph / test_query / test_bootstrap 测试因为错误格式变化而失败，需要相应调整这些测试中对 error 输出的断言。

- [ ] **Step 10: Commit**

```bash
git add skills/
git commit -m "fix(cli): move config loading into try, unify JSON error output and exit codes"
```

---

## Task 9: PR 1 最终验证

- [ ] **Step 1: 运行全量测试**

```bash
pytest tests/skills/ -v
```

期望：全部通过。

- [ ] **Step 2: grep 验证 — common.py / ovfs.py 中不再有 localhost 默认值**

```bash
grep -n "localhost:1933" skills/*/scripts/common.py skills/*/scripts/ovfs.py
```

期望：无输出。

- [ ] **Step 3: 确认共享脚本一致性**

```bash
pytest tests/skills/test_shared_script_consistency.py -v
```

期望：通过。

---

# PR 2：wiki-ingest source bundle 修复

## Task 10: 添加 IngestSourceError + IngestSourceBundle 数据结构

**Files:**
- Modify: `skills/wiki-ingest/scripts/ingest.py:14-15` (imports) + 新增代码

- [ ] **Step 1: 添加 import 和新的异常/数据类**

在 `skills/wiki-ingest/scripts/ingest.py` 的 import 区域，在已有的 `from common import ...` 行之后、`DEFAULT_LLM_CONFIG_PATH` 定义之前，添加：

```python
from dataclasses import dataclass


class IngestSourceError(RuntimeError):
    pass


IGNORED_SOURCE_MARKDOWN_NAMES = {
    ".abstract.md",
    ".overview.md",
    "abstract.md",
    "overview.md",
}


@dataclass
class IngestSourceBundle:
    root_uri: str
    markdown_uris: list[str]
    ignored_metadata_uris: list[str]
    source_kind: str
```

- [ ] **Step 2: Commit**

```bash
git add skills/wiki-ingest/scripts/ingest.py
git commit -m "feat(ingest): add IngestSourceBundle dataclass and IngestSourceError"
```

---

## Task 11: 添加通用 helper 函数

**Files:**
- Modify: `skills/wiki-ingest/scripts/ingest.py` (在 `get_uri_stat` 之后插入)

- [ ] **Step 1: 在 `get_uri_stat` 函数（第 163 行）之后插入以下函数**

```python
def is_ignored_source_markdown(uri: str) -> bool:
    name = PurePosixPath(uri.rstrip("/")).name
    return name in IGNORED_SOURCE_MARKDOWN_NAMES


def is_dir_stat(stat: dict[str, Any]) -> bool:
    if isinstance(stat.get("isDir"), bool):
        return stat["isDir"]
    if isinstance(stat.get("is_dir"), bool):
        return stat["is_dir"]
    if str(stat.get("type", "")).lower() in {"dir", "directory", "folder"}:
        return True
    return False


def extract_child_uri_and_is_dir(child: Any) -> tuple[str | None, bool | None]:
    if isinstance(child, str):
        return child, None

    if isinstance(child, dict):
        child_uri = child.get("uri") or child.get("path")
        child_is_dir: bool | None = None

        if isinstance(child.get("isDir"), bool):
            child_is_dir = child["isDir"]
        elif isinstance(child.get("is_dir"), bool):
            child_is_dir = child["is_dir"]
        elif str(child.get("type", "")).lower() in {"dir", "directory", "folder"}:
            child_is_dir = True

        return child_uri, child_is_dir

    return None, None
```

- [ ] **Step 2: Commit**

```bash
git add skills/wiki-ingest/scripts/ingest.py
git commit -m "feat(ingest): add is_dir_stat, extract_child_uri_and_is_dir, is_ignored_source_markdown"
```

---

## Task 12: 重构 find_direct_content_child 使用新 helpers

**Files:**
- Modify: `skills/wiki-ingest/scripts/ingest.py:166-217`

- [ ] **Step 1: 替换整个 `find_direct_content_child` 函数**

找到（从第 166 行开始的 `find_direct_content_child` 函数整体）：

```python
def find_direct_content_child(client: OVFSClient, uri: str, extensions: tuple[str, ...] = (".md",)) -> str | None:
    if not uri.endswith("/"):
        uri = uri.rstrip("/") + "/"
    try:
        children = client.ls(uri, recursive=False)
    except Exception:
        return None

    candidates: list[str] = []

    for child in children:
        child_uri: str | None = None
        child_is_dir: bool | None = None

        if isinstance(child, str):
            child_uri = child
        elif isinstance(child, dict):
            child_uri = child.get("uri") or child.get("path")
            if isinstance(child.get("isDir"), bool):
                child_is_dir = child["isDir"]

        if not child_uri or not isinstance(child_uri, str):
            continue

        name = PurePosixPath(child_uri).name

        if name == "abstract.md":
            continue

        if not name.endswith(extensions):
            continue

        if child_is_dir is None:
            child_stat = get_uri_stat(client, child_uri)
            child_is_dir = bool(child_stat and child_stat.get("isDir", False))

        if child_is_dir:
            continue

        candidates.append(child_uri)

    parent_name = PurePosixPath(uri.rstrip("/")).name

    for candidate in candidates:
        if PurePosixPath(candidate).name == parent_name:
            return candidate

    for candidate in candidates:
        if PurePosixPath(candidate).name.startswith("tmp"):
            return candidate

    return candidates[0] if candidates else None
```

替换为：

```python
def find_direct_content_child(client: OVFSClient, uri: str, extensions: tuple[str, ...] = (".md",)) -> str | None:
    if not uri.endswith("/"):
        uri = uri.rstrip("/") + "/"
    try:
        children = client.ls(uri, recursive=False)
    except Exception:
        return None

    candidates: list[str] = []

    for child in children:
        child_uri, child_is_dir_hint = extract_child_uri_and_is_dir(child)
        if not child_uri or not isinstance(child_uri, str):
            continue

        name = PurePosixPath(child_uri).name

        if is_ignored_source_markdown(child_uri):
            continue

        if not name.endswith(extensions):
            continue

        if child_is_dir_hint is None:
            child_stat = get_uri_stat(client, child_uri)
            child_is_dir_hint = bool(child_stat and is_dir_stat(child_stat))

        if child_is_dir_hint:
            continue

        candidates.append(child_uri)

    parent_name = PurePosixPath(uri.rstrip("/")).name

    for candidate in candidates:
        if PurePosixPath(candidate).name == parent_name:
            return candidate

    for candidate in candidates:
        if PurePosixPath(candidate).name.startswith("tmp"):
            return candidate

    return candidates[0] if candidates else None
```

- [ ] **Step 2: 运行现有 ingest 测试确认无回归**

```bash
pytest tests/skills/test_ingest_chunking.py -v
```

期望：全部通过。

- [ ] **Step 3: Commit**

```bash
git add skills/wiki-ingest/scripts/ingest.py
git commit -m "refactor(ingest): use extract_child_uri_and_is_dir in find_direct_content_child"
```

---

## Task 13: 添加 stat_uri_with_variants + discover + resolve + read 函数

**Files:**
- Modify: `skills/wiki-ingest/scripts/ingest.py` (在 `resolve_write_target_uri` 函数之前插入)

- [ ] **Step 1: 在 `resolve_write_target_uri` 函数之前插入以下全部函数**

```python
def stat_uri_with_variants(
    client: OVFSClient,
    uri: str,
) -> tuple[str, dict[str, Any]] | None:
    raw = uri.strip()
    if not raw:
        return None

    candidates = [raw]
    if raw.endswith("/"):
        candidates.append(raw.rstrip("/"))
    else:
        candidates.append(raw.rstrip("/") + "/")

    seen: set[str] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        stat = get_uri_stat(client, candidate)
        if stat:
            return candidate, stat

    return None


MAX_SOURCE_DISCOVERY_NODES = 1000


def natural_sort_key(text: str) -> list[Any]:
    return [
        int(x) if x.isdigit() else x.lower()
        for x in re.split(r"(\d+)", text)
    ]


def discover_markdown_sources_under_dir(
    client: OVFSClient,
    dir_uri: str,
) -> tuple[list[str], list[str]]:
    if not dir_uri.endswith("/"):
        dir_uri = dir_uri.rstrip("/") + "/"

    markdown_uris: list[str] = []
    ignored_metadata_uris: list[str] = []
    visited: set[str] = set()
    queue: list[str] = [dir_uri]
    nodes_scanned = 0

    while queue:
        current_dir = queue.pop(0)
        if current_dir in visited:
            continue
        visited.add(current_dir)
        nodes_scanned += 1

        if nodes_scanned > MAX_SOURCE_DISCOVERY_NODES:
            raise IngestSourceError(
                f"source bundle 过大或存在循环，已停止扫描; scanned={nodes_scanned}"
            )

        try:
            children = client.ls(current_dir, recursive=False)
        except OVFSHTTPError as exc:
            msg = str(exc).lower()
            if "404" in msg or "not found" in msg:
                continue
            raise IngestSourceError(f"扫描目录失败: {current_dir}: {exc}") from exc
        except Exception as exc:
            raise IngestSourceError(f"扫描目录失败: {current_dir}: {exc}") from exc

        for child in children:
            child_uri, child_is_dir_hint = extract_child_uri_and_is_dir(child)
            if not child_uri or not isinstance(child_uri, str):
                continue

            if child_is_dir_hint is None:
                child_resolved = stat_uri_with_variants(client, child_uri)
                if child_resolved:
                    child_uri = child_resolved[0]
                    child_is_dir_hint = is_dir_stat(child_resolved[1])

            if child_is_dir_hint:
                queue.append(child_uri if child_uri.endswith("/") else child_uri + "/")
                continue

            if not child_uri.lower().endswith(".md"):
                continue

            if is_ignored_source_markdown(child_uri):
                ignored_metadata_uris.append(child_uri)
                continue

            markdown_uris.append(child_uri)

    markdown_uris = sorted(set(markdown_uris), key=natural_sort_key)
    ignored_metadata_uris = sorted(set(ignored_metadata_uris), key=natural_sort_key)
    return markdown_uris, ignored_metadata_uris


def resolve_ingest_source_bundle(
    client: OVFSClient,
    source_uri: str,
) -> IngestSourceBundle:
    resolved = stat_uri_with_variants(client, source_uri)
    if not resolved:
        raise IngestSourceError(f"Source not found: {source_uri}")

    resolved_uri, stat = resolved

    if is_dir_stat(stat):
        markdown_uris, ignored_metadata_uris = discover_markdown_sources_under_dir(
            client, resolved_uri,
        )

        if not markdown_uris:
            if ignored_metadata_uris:
                raise IngestSourceError(
                    "未找到可 ingest 的正文 markdown。"
                    "该目录下只有 metadata markdown，已跳过。"
                )
            raise IngestSourceError(
                "未找到可 ingest 的 markdown。"
                "可能是上传转换尚未完成，或 source-uri 指错。"
            )

        return IngestSourceBundle(
            root_uri=resolved_uri,
            markdown_uris=markdown_uris,
            ignored_metadata_uris=ignored_metadata_uris,
            source_kind=(
                "directory_single_markdown"
                if len(markdown_uris) == 1
                else "directory_bundle"
            ),
        )

    if resolved_uri.lower().endswith(".md"):
        if is_ignored_source_markdown(resolved_uri):
            raise IngestSourceError(
                f"该 markdown 是 metadata 文件，不能 ingest: {resolved_uri}"
            )
        return IngestSourceBundle(
            root_uri=resolved_uri,
            markdown_uris=[resolved_uri],
            ignored_metadata_uris=[],
            source_kind="single_markdown_file",
        )

    raise IngestSourceError(
        f"该 source 不是可 ingest 的 markdown 文件，也不是包含 markdown 的目录: {resolved_uri}"
    )


def read_source_bundle_text(
    client: OVFSClient,
    bundle: IngestSourceBundle,
) -> str:
    parts: list[str] = []
    total = len(bundle.markdown_uris)
    for idx, uri in enumerate(bundle.markdown_uris, start=1):
        content = client.read_text(uri)
        parts.append(f"--- SOURCE FILE {idx}/{total} ---")
        parts.append(f"URI: {uri}")
        parts.append("")
        parts.append(content)
        parts.append("")
    return "\n".join(parts)


def source_name_from_uri(uri: str) -> str:
    return PurePosixPath(uri.rstrip("/")).name


def source_title_stem_from_uri(uri: str) -> str:
    name = source_name_from_uri(uri)
    suffixes = [
        ".docx", ".doc", ".pdf", ".md", ".txt",
        ".json", ".yaml", ".yml", ".sh", ".py",
    ]
    lower = name.lower()
    for suffix in suffixes:
        if lower.endswith(suffix):
            return name[: -len(suffix)]
    return name
```

- [ ] **Step 2: Commit**

```bash
git add skills/wiki-ingest/scripts/ingest.py
git commit -m "feat(ingest): add source bundle discovery, resolve, and read functions"
```

---

## Task 14: 写 source bundle 单元测试

**Files:**
- Create: `tests/skills/test_ingest_source_bundle.py`

- [ ] **Step 1: 写出完整测试文件**

```python
from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys

import pytest


repoRoot = Path(__file__).resolve().parents[2]
scriptsDir = repoRoot / "skills" / "wiki-ingest" / "scripts"
modulePath = scriptsDir / "ingest.py"
sys.path.insert(0, str(scriptsDir))
spec = spec_from_file_location("wiki_ingest_bundle", modulePath)
if spec is None or spec.loader is None:
    raise RuntimeError("无法加载 skills/wiki-ingest/scripts/ingest.py")
module = module_from_spec(spec)
spec.loader.exec_module(module)

IngestSourceError = module.IngestSourceError
IngestSourceBundle = module.IngestSourceBundle
resolve_ingest_source_bundle = module.resolve_ingest_source_bundle
is_ignored_source_markdown = module.is_ignored_source_markdown


class FakeBundleClient:
    def __init__(
        self,
        dirs: dict[str, list[dict[str, object]]] | None = None,
        files: dict[str, str] | None = None,
    ) -> None:
        self.dirs = dirs or {}
        self.files = files or {}

    def stat(self, uri: str) -> dict:
        key = uri.rstrip("/")
        if key in self.files:
            return {"isDir": False}
        if key in self.dirs or uri in self.dirs:
            return {"isDir": True}
        if uri.endswith("/") and uri.rstrip("/") in self.dirs:
            return {"isDir": True}
        raise module.OVFSHTTPError("404 not found")

    def ls(self, uri: str, recursive: bool = False) -> list:
        key = uri.rstrip("/") + "/"
        if key in self.dirs:
            return self.dirs[key]
        if uri.rstrip("/") in self.dirs:
            return self.dirs[uri.rstrip("/")]
        return []

    def read_text(self, uri: str) -> str:
        key = uri.rstrip("/")
        if key in self.files:
            return self.files[key]
        raise module.OVFSHTTPError(f"404 not found: {uri}")


BASE = "viking://resources/demo/raw"


def test_md_directory_bundle_with_subdirs() -> None:
    root = f"{BASE}/ingest超时记录.md"
    dirs = {
        root: [
            {"uri": f"{root}/.abstract.md", "isDir": False},
            {"uri": f"{root}/.overview.md", "isDir": False},
            {"uri": f"{root}/OpenCode_会话记录知识库初始化", "isDir": True},
            {"uri": f"{root}/Skill_wiki-upload-source_853763ae.md", "isDir": False},
        ],
        f"{root}/OpenCode_会话记录知识库初始化": [
            {"uri": f"{root}/OpenCode_会话记录知识库初始化/.abstract.md", "isDir": False},
            {"uri": f"{root}/OpenCode_会话记录知识库初始化/.overview.md", "isDir": False},
            {"uri": f"{root}/OpenCode_会话记录知识库初始化/part1.md", "isDir": False},
            {"uri": f"{root}/OpenCode_会话记录知识库初始化/part2.md", "isDir": False},
        ],
    }
    files = {
        f"{root}/.abstract.md": "abstract",
        f"{root}/.overview.md": "overview",
        f"{root}/OpenCode_会话记录知识库初始化/.abstract.md": "abstract",
        f"{root}/OpenCode_会话记录知识库初始化/.overview.md": "overview",
        f"{root}/OpenCode_会话记录知识库初始化/part1.md": "content1",
        f"{root}/OpenCode_会话记录知识库初始化/part2.md": "content2",
        f"{root}/Skill_wiki-upload-source_853763ae.md": "content3",
    }
    client = FakeBundleClient(dirs=dirs, files=files)
    bundle = resolve_ingest_source_bundle(client, root)

    assert bundle.source_kind == "directory_bundle"
    assert len(bundle.markdown_uris) == 3
    assert f"{root}/OpenCode_会话记录知识库初始化/part1.md" in bundle.markdown_uris
    assert f"{root}/OpenCode_会话记录知识库初始化/part2.md" in bundle.markdown_uris
    assert f"{root}/Skill_wiki-upload-source_853763ae.md" in bundle.markdown_uris
    assert not any(".abstract.md" in u for u in bundle.markdown_uris)
    assert not any(".overview.md" in u for u in bundle.markdown_uris)
    assert len(bundle.ignored_metadata_uris) >= 2


def test_sh_directory_bundle() -> None:
    root = f"{BASE}/install-llm-wiki.sh"
    dirs = {
        root: [
            {"uri": f"{root}/.abstract.md", "isDir": False},
            {"uri": f"{root}/.overview.md", "isDir": False},
            {"uri": f"{root}/install-llm-wiki_1.md", "isDir": False},
            {"uri": f"{root}/install-llm-wiki_2.md", "isDir": False},
        ],
    }
    files = {
        f"{root}/.abstract.md": "abstract",
        f"{root}/.overview.md": "overview",
        f"{root}/install-llm-wiki_1.md": "c1",
        f"{root}/install-llm-wiki_2.md": "c2",
    }
    client = FakeBundleClient(dirs=dirs, files=files)
    bundle = resolve_ingest_source_bundle(client, root)

    assert bundle.source_kind == "directory_bundle"
    assert len(bundle.markdown_uris) == 2


def test_json_directory_single_markdown() -> None:
    root = f"{BASE}/llm-wiki-config-ZH-0737.json"
    dirs = {
        root: [
            {"uri": f"{root}/.abstract.md", "isDir": False},
            {"uri": f"{root}/.overview.md", "isDir": False},
            {"uri": f"{root}/llm-wiki-config-ZH-0737.md", "isDir": False},
        ],
    }
    files = {
        f"{root}/.abstract.md": "abstract",
        f"{root}/.overview.md": "overview",
        f"{root}/llm-wiki-config-ZH-0737.md": "content",
    }
    client = FakeBundleClient(dirs=dirs, files=files)
    bundle = resolve_ingest_source_bundle(client, root)

    assert bundle.source_kind == "directory_single_markdown"
    assert bundle.markdown_uris == [f"{root}/llm-wiki-config-ZH-0737.md"]


def test_single_md_file() -> None:
    uri = f"{BASE}/manual.md"
    files = {uri: "manual content"}
    client = FakeBundleClient(files=files)
    bundle = resolve_ingest_source_bundle(client, uri)

    assert bundle.source_kind == "single_markdown_file"
    assert bundle.markdown_uris == [uri]


def test_no_trailing_slash_resolves_to_directory() -> None:
    root = f"{BASE}/install-llm-wiki.sh"
    dirs_with_slash = {
        root + "/": [
            {"uri": f"{root}/install-llm-wiki_1.md", "isDir": False},
        ],
    }
    files = {
        f"{root}/install-llm-wiki_1.md": "c1",
    }
    client = FakeBundleClient(dirs=dirs_with_slash, files=files)
    bundle = resolve_ingest_source_bundle(client, root)

    assert bundle.source_kind == "directory_single_markdown"
    assert len(bundle.markdown_uris) == 1


def test_directory_only_metadata_raises() -> None:
    root = f"{BASE}/empty.md"
    dirs = {
        root: [
            {"uri": f"{root}/.abstract.md", "isDir": False},
            {"uri": f"{root}/.overview.md", "isDir": False},
        ],
    }
    files = {
        f"{root}/.abstract.md": "abstract",
        f"{root}/.overview.md": "overview",
    }
    client = FakeBundleClient(dirs=dirs, files=files)

    with pytest.raises(IngestSourceError, match="只有 metadata markdown"):
        resolve_ingest_source_bundle(client, root)


def test_non_md_file_raises() -> None:
    uri = f"{BASE}/a.json"
    files = {uri: "{}"}
    client = FakeBundleClient(files=files)

    with pytest.raises(IngestSourceError, match="不是可 ingest 的 markdown"):
        resolve_ingest_source_bundle(client, uri)


def test_source_not_found_raises() -> None:
    client = FakeBundleClient()

    with pytest.raises(IngestSourceError, match="Source not found"):
        resolve_ingest_source_bundle(client, f"{BASE}/nonexistent.md")


def test_is_ignored_source_markdown() -> None:
    assert is_ignored_source_markdown("foo/.abstract.md")
    assert is_ignored_source_markdown("foo/.overview.md")
    assert is_ignored_source_markdown("foo/abstract.md")
    assert is_ignored_source_markdown("foo/overview.md")
    assert not is_ignored_source_markdown("foo/real-content.md")
    assert not is_ignored_source_markdown("foo/Abstract.md")
```

- [ ] **Step 2: 运行测试验证**

```bash
pytest tests/skills/test_ingest_source_bundle.py -v
```

期望：全部通过。

- [ ] **Step 3: Commit**

```bash
git add tests/skills/test_ingest_source_bundle.py
git commit -m "test(ingest): add source bundle unit tests"
```

---

## Task 15: 修改 build_llm_prompt 添加可选 source_markdown_uris

**Files:**
- Modify: `skills/wiki-ingest/scripts/ingest.py:533-619`

- [ ] **Step 1: 修改 build_llm_prompt 签名和内容**

找到 `build_llm_prompt` 函数签名（第 533 行）：

```python
def build_llm_prompt(
    schema_text: str,
    source_uri: str,
    source_text: str,
    context: Dict[str, Any],
    source_slug: str,
) -> str:
```

替换为：

```python
def build_llm_prompt(
    schema_text: str,
    source_uri: str,
    source_text: str,
    context: Dict[str, Any],
    source_slug: str,
    source_markdown_uris: list[str] | None = None,
) -> str:
```

然后，在函数体中找到：

```python
    return f"""
你正在为基于远端 OpenViking 的 llm-wiki 知识库生成 wiki 内容。
```

在这个 f-string 开头的 `"""` 之前插入 bundle 说明构建代码：

```python
    bundle_section = ""
    if source_markdown_uris:
        uri_list = "\n".join(f"- {u}" for u in source_markdown_uris)
        bundle_section = f"""
本次 ingest 的 source root URI：
{source_uri}

本次 ingest 包含的正文 markdown URI：
{uri_list}

注意：.abstract.md 和 .overview.md 属于 metadata，不能作为正文来源。

"""
```

然后修改 f-string，在 `当前 source URI` 之前插入 bundle_section：

找到 f-string 中的：

```text
你正在为基于远端 OpenViking 的 llm-wiki 知识库生成 wiki 内容。

请严格遵循以下 schema：
```

替换为：

```text
你正在为基于远端 OpenViking 的 llm-wiki 知识库生成 wiki 内容。
{bundle_section}请严格遵循以下 schema：
```

注意：`{bundle_section}` 后面不需要额外空行，因为 bundle_section 本身以 `\n\n` 结尾。

- [ ] **Step 2: 运行测试确认无回归**

```bash
pytest tests/skills/test_ingest_chunking.py -v
```

期望：全部通过。因为 `source_markdown_uris` 默认为 `None`，bundle_section 为空字符串，不影响现有行为。

- [ ] **Step 3: Commit**

```bash
git add skills/wiki-ingest/scripts/ingest.py
git commit -m "feat(ingest): add optional source_markdown_uris to build_llm_prompt"
```

---

## Task 16: 修改 main() 使用 source bundle + 更新输出 JSON

**Files:**
- Modify: `skills/wiki-ingest/scripts/ingest.py:972-984` (source 解析)
- Modify: `skills/wiki-ingest/scripts/ingest.py:1011-1013` (summarize_chunk 调用)
- Modify: `skills/wiki-ingest/scripts/ingest.py:1049-1055` (build_llm_prompt 调用)
- Modify: `skills/wiki-ingest/scripts/ingest.py:1118-1149` (结果 JSON)

- [ ] **Step 1: 替换 main() 中的 source 解析（第 972-984 行）**

找到（在 Task 8 修改后的代码中）：

```python
            canonical_source_uri = resolve_canonical_markdown_uri(client, args.source_uri)
            if not canonical_source_uri:
                raise OVFSHTTPError(f"File not found: {args.source_uri}")

            source_text = client.read_text(canonical_source_uri)
            context = build_context_snapshot(
                client,
                kb_root,
                max_context_chars=args.max_context_chars,
                max_existing_page_names=args.max_existing_page_names,
            )

            source_slug = slugify(basename_without_ext(args.source_uri))
```

替换为：

```python
            source_bundle = resolve_ingest_source_bundle(client, args.source_uri)
            source_text = read_source_bundle_text(client, source_bundle)
            context = build_context_snapshot(
                client,
                kb_root,
                max_context_chars=args.max_context_chars,
                max_existing_page_names=args.max_existing_page_names,
            )

            source_slug = slugify(source_title_stem_from_uri(source_bundle.root_uri))
```

- [ ] **Step 2: 修改 summarize_chunk 调用中的 source_uri**

找到（约第 1011 行）：

```python
                        summary = summarize_chunk(
                            source_uri=args.source_uri,
                            source_slug=source_slug,
```

替换为：

```python
                        summary = summarize_chunk(
                            source_uri=source_bundle.root_uri,
                            source_slug=source_slug,
```

- [ ] **Step 3: 修改 build_llm_prompt 调用**

找到（约第 1049 行）：

```python
            prompt = build_llm_prompt(
                schema_text=schema_text,
                source_uri=args.source_uri,
                source_text=source_for_reduce,
                context=context,
                source_slug=source_slug,
            )
```

替换为：

```python
            prompt = build_llm_prompt(
                schema_text=schema_text,
                source_uri=source_bundle.root_uri,
                source_text=source_for_reduce,
                context=context,
                source_slug=source_slug,
                source_markdown_uris=source_bundle.markdown_uris,
            )
```

- [ ] **Step 4: 修改成功输出 JSON**

找到（约第 1118 行）：

```python
            result = {
                "status": "ok",
                "kb_root": kb_root,
                "source_uri": args.source_uri,
```

替换为：

```python
            result = {
                "status": "ok",
                "kb_root": kb_root,
                "input_source_uri": args.source_uri,
                "source_uri": source_bundle.root_uri,
                "source_root_uri": source_bundle.root_uri,
                "source_kind": source_bundle.source_kind,
                "source_markdown_count": len(source_bundle.markdown_uris),
                "source_markdown_uris": source_bundle.markdown_uris,
                "ignored_metadata_uris": source_bundle.ignored_metadata_uris,
```

保留后续原有字段（source_slug、source_title 等）不变。

- [ ] **Step 5: 修改错误输出 JSON**

找到（约第 1151 行）：

```python
    except Exception as exc:
        error_result = {
            "status": "error",
            "kb_root": kb_root,
            "source_uri": args.source_uri,
            "error": str(exc),
        }
        print(json.dumps(error_result, ensure_ascii=False, indent=2))
        return 1
```

替换为：

```python
    except Exception as exc:
        from common import build_error_result, print_json
        print_json(build_error_result(
            exc, kb_root=kb_root, input_source_uri=args.source_uri,
        ), pretty=args.pretty)
        return 1
```

注意：此处 `print_json` 和 `build_error_result` 来自 common.py。PR1 Task 8 已经在 import 行添加了这些符号：

```python
from common import build_error_result, build_kb_root, load_config, print_json
```

如果该行已经存在，无需再修改 import。仅当 `print_json` 缺失时才需补充。

- [ ] **Step 6: 运行测试验证**

```bash
pytest tests/skills/test_ingest_chunking.py tests/skills/test_ingest_source_bundle.py -v
```

如果 test_ingest_chunking.py 中的 FakeOVFSClient 的 `stat()` 不兼容 source bundle（因为 `resolve_canonical_markdown_uri` 被替换为 `resolve_ingest_source_bundle`），需要调整 FakeOVFSClient。

调整方式：在 `test_ingest_chunking.py` 的 `FakeOVFSClient.__init__` 中，确保 `source_uri` 对应的 stat 返回 `{"isDir": False}`，并且 `ls()` 对 raw 目录不返回子项（因为 source 是单文件，不是 bundle）。

当前 FakeOVFSClient 的 `stat()` 已经对 `self.source_uri` 返回 `{"isDir": False}`，`ls()` 对 raw 目录返回空列表。但 `resolve_ingest_source_bundle` 会先调用 `stat_uri_with_variants`，然后因为 `isDir: False` 且以 `.md` 结尾，会走到 `single_markdown_file` 分支。这应该能正常工作。

如果有问题，需要在 test_ingest_chunking.py 的 FakeOVFSClient 中添加对 `stat_uri_with_variants` 调用的支持（确保无 trailing slash 也能 stat 到文件）。

- [ ] **Step 7: Commit**

```bash
git add skills/wiki-ingest/scripts/ingest.py
git commit -m "feat(ingest): integrate source bundle into main flow and output JSON"
```

---

## Task 17: 更新 upload.py 返回值

**Files:**
- Modify: `skills/wiki-upload-source/scripts/upload.py:63-70`

- [ ] **Step 1: 修改 runUpload 返回值**

找到：

```python
  return {
    "kb_name": normalizedKbName,
    "kb_root": kbRoot,
    "source_file": str(sourcePath),
    "target_uri": targetUri,
    "wait": waitForCompletion,
    "uploaded": True,
  }
```

替换为：

```python
  return {
    "kb_name": normalizedKbName,
    "kb_root": kbRoot,
    "source_file": str(sourcePath),
    "target_uri": targetUri,
    "suggested_ingest_uri": targetUri,
    "next_step": "可使用 suggested_ingest_uri 调用 wiki-ingest。OpenViking 可能会将该资源转换为同名目录 bundle，wiki-ingest 会自动递归查找正文 markdown。",
    "wait": waitForCompletion,
    "uploaded": True,
  }
```

- [ ] **Step 2: 运行相关测试**

```bash
pytest tests/skills/test_upload_target_path.py -v
```

如果有测试断言 upload 返回值的固定字段数，需要调整。

- [ ] **Step 3: Commit**

```bash
git add skills/wiki-upload-source/scripts/upload.py
git commit -m "feat(upload): add suggested_ingest_uri and next_step to upload result"
```

---

## Task 18: 更新 SKILL.md 文件

**Files:**
- Modify: `skills/wiki-ingest/SKILL.md`
- Modify: `skills/wiki-upload-source/SKILL.md`

- [ ] **Step 1: 更新 wiki-ingest/SKILL.md**

在 SKILL.md 中，找到示例命令中的硬编码路径（如果有 `/home/user/...`），替换为 `$HOME`。

添加以下说明（在合适位置）：

```markdown
当用户要求 ingest raw 中某个上传资源时，不要假设 raw/<name> 是单个文件。
OpenViking 可能把任意上传文件转换成 raw/<name>/ 目录 bundle。
该 bundle 下可能包含 .abstract.md、.overview.md、正文 md 和多层子目录。
wiki-ingest 会递归查找正文 md，并跳过 metadata md。
```

如果用户只给自然语言描述没有给 source-uri，添加说明：

```markdown
如果用户只给自然语言描述，没有给 source-uri，先浏览 raw/ 目录定位最匹配的 raw source bundle URI，再把该 URI 传给 --source-uri。
```

- [ ] **Step 2: 更新 wiki-upload-source/SKILL.md**

在 SKILL.md 中添加说明：

```markdown
上传成功后，返回结果中包含 suggested_ingest_uri 和 next_step。
OpenViking 可能会将上传的资源转换为同名目录 bundle。
使用 suggested_ingest_uri 调用 wiki-ingest 即可，wiki-ingest 会自动处理。
```

- [ ] **Step 3: Commit**

```bash
git add skills/wiki-ingest/SKILL.md skills/wiki-upload-source/SKILL.md
git commit -m "docs: update SKILL.md for source bundle and upload return values"
```

---

## Task 19: PR 2 最终验证

- [ ] **Step 1: 运行全量测试**

```bash
pytest tests/skills/ -v
```

期望：全部通过。

- [ ] **Step 2: grep 验证**

```bash
grep -R "http://localhost:1933" skills/*/scripts/common.py skills/*/scripts/ovfs.py
```

期望：无输出。

- [ ] **Step 3: 确认 docx 特判不存在**

```bash
grep -n 'docx_bundle\|resolve_docx\|endswith.*docx' skills/wiki-ingest/scripts/ingest.py
```

期望：无输出。（注意：source_title_stem_from_uri 中的 ".docx" 是合法的 slug 去后缀用途，不在检查范围内）

- [ ] **Step 4: 确认 source bundle 函数齐全**

```bash
grep -n "def resolve_ingest_source_bundle\|def discover_markdown_sources_under_dir\|def read_source_bundle_text\|def stat_uri_with_variants\|class IngestSourceBundle\|class IngestSourceError" skills/wiki-ingest/scripts/ingest.py
```

期望：每项都有一个匹配。

- [ ] **Step 5: 确认 resolve_canonical_markdown_uri 仍存在**

```bash
grep -n "def resolve_canonical_markdown_uri" skills/wiki-ingest/scripts/ingest.py
```

期望：有输出。

---

## 禁止事项检查清单

实现完成后逐项确认：

- [ ] 未只修 wiki-upload-source
- [ ] 未只修 wiki-ingest
- [ ] common.py / ovfs.py 中无 localhost 默认值
- [ ] profile 找不到时直接报错而非继续执行
- [ ] 未恢复 OPENVIKING_* 环境变量读取
- [ ] 未引入 LLM_WIKI_CONFIG 环境变量读取
- [ ] 未根据 .docx 后缀判断 source bundle
- [ ] 未根据 .md 后缀直接判断是单文件（先 stat 再判断）
- [ ] 未 ingest .abstract.md / .overview.md
- [ ] resolve_canonical_markdown_uri 仍存在
- [ ] 未依赖 client.ls(..., recursive=True) 解决 source bundle 递归
- [ ] wiki-profile 与其他 skills 使用同一套 profile 解析逻辑
- [ ] 未输出未脱敏 API key
- [ ] 未实现 --source-query
