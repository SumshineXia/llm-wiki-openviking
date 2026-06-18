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


def test_profile_cli_rejects_deprecated_defaults(tmp_path: Path) -> None:
    config_path = tmp_path / "old-config.json"
    config_path.write_text(
        json.dumps(
            {
                "version": 2,
                "profiles": [
                    {
                        "profile": "p1",
                        "system": {"name": "System 1", "ipmp_system_num": "IPMP-1"},
                        "openviking": {"url": "http://p1:1933"},
                        "defaults": {"kb_name": "old-default"}
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    env = _make_env(tmp_path)

    exit_code, payload = _run_allow_fail(["--config", str(config_path), "list"], tmp_path, env)

    assert exit_code == 1
    assert payload["status"] == "error"
    assert "ConfigError" in payload.get("error_type", "")
    assert "已废弃字段 defaults" in payload.get("error", "")
