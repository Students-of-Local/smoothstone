"""stone.toml: the nearest file wins per key, and tables merge."""
from smoothstone import config


def test_a_job_stone_toml_with_only_a_tier_keeps_the_machine_filaments(tmp_path, monkeypatch):
    machine = tmp_path / "xdg" / "smoothstone"
    machine.mkdir(parents=True)
    (machine / "stone.toml").write_text('bed = [180, 180, 180]\n[filaments]\n1 = "white"\n2 = "black"\n3 = "red"\n')
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    job = tmp_path / "job"
    job.mkdir()
    (job / "stone.toml").write_text('tier = "M"\n')
    monkeypatch.chdir(tmp_path)
    assert config.tier(job) == "M"
    assert config.filaments(job) == ["white", "black", "red"]
    assert config.bed(job) == (180.0, 180.0, 180.0)


def test_nearest_file_wins_per_key_and_tables_merge_by_key(tmp_path, monkeypatch):
    machine = tmp_path / "xdg" / "smoothstone"
    machine.mkdir(parents=True)
    (machine / "stone.toml").write_text('tier = "S"\n[filaments]\n1 = "white"\n2 = "black"\n')
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    job = tmp_path / "job"
    job.mkdir()
    (job / "stone.toml").write_text('[filaments]\n2 = "blue"\n')
    cwd = tmp_path / "here"
    cwd.mkdir()
    (cwd / "stone.toml").write_text('tier = "L"\n')
    monkeypatch.chdir(cwd)
    assert config.tier(job) == "L"
    assert config.filaments(job) == ["white", "blue"]


def test_a_broken_stone_toml_is_skipped_not_fatal(tmp_path, monkeypatch):
    machine = tmp_path / "xdg" / "smoothstone"
    machine.mkdir(parents=True)
    (machine / "stone.toml").write_text('[filaments]\n1 = "red"\n2 = "blue"\n')
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    job = tmp_path / "job"
    job.mkdir()
    (job / "stone.toml").write_text('tier = \n')
    monkeypatch.chdir(tmp_path)
    assert config.filaments(job) == ["red", "blue"]
