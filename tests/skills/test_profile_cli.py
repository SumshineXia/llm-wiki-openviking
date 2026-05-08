import json
import os
from pathlib import Path
import subprocess


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
            "openviking": {"api_key": "12345678"},
            "openai": {"api_key": "abcd1234efgh5678"},
          },
          {
            "profile": "p2",
            "openviking": {"api_key": "p2-openviking-key"},
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


def test_profile_cli_list_use_show_bind_unbind_current_sources(tmp_path: Path, monkeypatch) -> None:
  config_path = tmp_path / "config.json"
  _write_config(config_path)

  config_home = tmp_path / "home"
  monkeypatch.setenv("HOME", str(config_home))
  monkeypatch.delenv("LLM_WIKI_PROFILE", raising=False)

  env = dict(os.environ)
  env["HOME"] = str(config_home)
  env.pop("LLM_WIKI_PROFILE", None)

  listed = _run(["--config", str(config_path), "list"], tmp_path, env)
  assert listed["profiles"] == ["p1", "p2"]

  current_default = _run(["--config", str(config_path), "current"], tmp_path, env)
  assert current_default["profile"] == "p1"
  assert current_default["source"] == "profiles[0]"

  current_cli = _run(["--config", str(config_path), "--profile", "p2", "current"], tmp_path, env)
  assert current_cli["profile"] == "p2"
  assert current_cli["source"] == "--profile"

  env_with_llm_profile = dict(env)
  env_with_llm_profile["LLM_WIKI_PROFILE"] = "p2"
  current_env = _run(["--config", str(config_path), "current"], tmp_path, env_with_llm_profile)
  assert current_env["profile"] == "p2"
  assert current_env["source"] == "LLM_WIKI_PROFILE"

  work_dir = tmp_path / "workspace" / "a" / "b"
  work_dir.mkdir(parents=True, exist_ok=True)
  (tmp_path / "workspace" / ".llm-wiki-profile").write_text("p2\n", encoding="utf-8")
  current_marker = _run(["--config", str(config_path), "current"], work_dir, env)
  assert current_marker["profile"] == "p2"
  assert current_marker["source"] == ".llm-wiki-profile"

  used = _run(["--config", str(config_path), "use", "p2"], tmp_path, env)
  assert used["profile"] == "p2"

  current_file = _run(["--config", str(config_path), "current"], tmp_path, env)
  assert current_file["profile"] == "p2"
  assert current_file["source"] == "current"

  shown = _run(["--config", str(config_path), "show", "p1"], tmp_path, env)
  assert shown["data"]["openviking"]["api_key"] == "********"
  assert shown["data"]["openai"]["api_key"] == "abcd********5678"

  bind_dir = tmp_path / "bind-dir"
  bound = _run(["--config", str(config_path), "bind", "p1", "--dir", str(bind_dir)], tmp_path, env)
  assert Path(bound["marker"]).exists()

  unbound = _run(["--config", str(config_path), "unbind", "--dir", str(bind_dir)], tmp_path, env)
  assert unbound["removed"] is True
  assert not (bind_dir / ".llm-wiki-profile").exists()
