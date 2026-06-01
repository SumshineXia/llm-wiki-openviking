# Test Baseline Before Save Query Perf

**Command:** `python3 -m pytest tests/skills -q`

**Initial Result:** `4 failed, 119 passed, 1 warning in 3.82s`

**Known Failures:**
- `tests/skills/test_common_load_config.py::test_load_config_uses_first_profile_by_default`：与本次 profile 隔离相关，必须修复。
- `tests/skills/test_common_load_config.py::test_load_config_uses_llm_wiki_config_env`：与“配置只读 config”目标冲突，必须删除或改成验证 `LLM_WIKI_CONFIG` 不再生效。
- `tests/skills/test_resolve_write_target.py::test_write_page_creates_via_write_text`：与本次 write helper 相关，必须修复。
- `tests/skills/test_shared_script_consistency.py::test_ovfs_py_files_are_consistent`：与新增 `wiki-save` 共享脚本相关，必须修复。

**Resolution:** Phase 0 修复后要求 `tests/skills` 全绿，再进入功能改造。
