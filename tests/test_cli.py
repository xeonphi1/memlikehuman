import json
from pathlib import Path

from memlikehuman.cli import main


def test_cli_roundtrip_persona_config_backup_and_restore(tmp_path, capsys):
    data = tmp_path / "data"
    base = ["--data-dir", str(data)]
    assert main([*base, "init"]) == 0
    assert json.loads(capsys.readouterr().out)["initialized"]
    root = Path(__file__).resolve().parents[1]
    assert main([*base, "record", str(root / "examples/event.json")]) == 0
    assert (
        main([*base, "derive", "synthetic-demo-001", str(root / "examples/extraction.json")]) == 0
    )
    assert main([*base, "persona", "--file", str(root / "examples/persona.json")]) == 0
    capsys.readouterr()
    assert main([*base, "persona", "--rollback", "1"]) == 0
    assert json.loads(capsys.readouterr().out)["version"] == 3
    backup = tmp_path / "backup.sqlite3"
    assert main([*base, "backup", str(backup)]) == 0
    restored = ["--data-dir", str(tmp_path / "restored")]
    assert main([*restored, "restore", str(backup)]) == 0
    capsys.readouterr()
    assert main([*restored, "recall", "测试"]) == 0
    assert json.loads(capsys.readouterr().out)["memories"]
    # Bad configuration never overwrites the existing one.
    invalid = tmp_path / "bad.json"
    invalid.write_text('{"api_key":"must-not-save"}')
    before = (data / "config.json").read_text()
    assert main([*base, "config", "--file", str(invalid)]) == 1
    assert (data / "config.json").read_text() == before
    assert "must-not-save" not in capsys.readouterr().err
