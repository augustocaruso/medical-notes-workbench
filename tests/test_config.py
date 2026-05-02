from pathlib import Path

from enricher import config


def test_find_config_falls_back_to_persistent_user_dir(monkeypatch, tmp_path: Path):
    state = tmp_path / "state"
    state.mkdir()
    user_config = state / "config.toml"
    user_config.write_text("[vault]\npath = \"~/Vault\"\n", encoding="utf-8")
    work = tmp_path / "work"
    work.mkdir()

    monkeypatch.setenv("MEDNOTES_HOME", str(state))
    monkeypatch.delenv("MEDNOTES_CONFIG", raising=False)
    monkeypatch.delenv("MEDICAL_NOTES_CONFIG", raising=False)
    monkeypatch.chdir(work)

    assert config.find_config() == user_config


def test_find_config_env_var_has_priority(monkeypatch, tmp_path: Path):
    state = tmp_path / "state"
    state.mkdir()
    (state / "config.toml").write_text("[vault]\npath = \"~/Persistent\"\n", encoding="utf-8")
    explicit = tmp_path / "chosen.toml"
    explicit.write_text("[vault]\npath = \"~/Chosen\"\n", encoding="utf-8")

    monkeypatch.setenv("MEDNOTES_HOME", str(state))
    monkeypatch.setenv("MEDNOTES_CONFIG", str(explicit))

    assert config.find_config() == explicit
