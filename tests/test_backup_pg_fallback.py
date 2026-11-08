"""pg_dump 宿主机缺失时回退 Docker 的契约测试。"""
from __future__ import annotations

from scripts import backup_control_plane as backup


def test_pg_dump_falls_back_to_docker(monkeypatch, tmp_path):
    monkeypatch.setattr(backup.shutil, "which", lambda name: "docker" if name == "docker" else None)
    target = tmp_path / "vec_db.dump"
    calls = []

    def fake_run(command, check, stdout, stderr, timeout):
        calls.append(command)
        stdout.write(b"PGDMP" + b"0" * 20)
        return type("Result", (), {"returncode": 0})()

    monkeypatch.setattr(backup.subprocess, "run", fake_run)
    result = backup._pg_dump(target)
    assert result["ok"] is True
    assert result["mode"] == "docker"
    assert calls and calls[0][0] == "docker"
    assert "exec" in calls[0] and "pg_dump" in calls[0]
    assert calls[0][-1] == "-Fc"
    assert target.read_bytes().startswith(b"PGDMP")
