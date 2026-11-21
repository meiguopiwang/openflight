"""Atomic JSON persistence shared by saved calibrations."""

import json

import pytest

from openflight import json_files
from openflight.json_files import atomic_write_json


def test_writes_indented_sorted_json_with_trailing_newline(tmp_path):
    path = tmp_path / "nested" / "dir" / "record.json"

    atomic_write_json(path, {"b": 1, "a": [1, 2]})

    text = path.read_text(encoding="utf-8")
    assert text == json.dumps({"a": [1, 2], "b": 1}, indent=2, sort_keys=True) + "\n"


def test_replaces_an_existing_file_and_leaves_no_temporary_files(tmp_path):
    path = tmp_path / "record.json"
    path.write_text('{"old": true}\n', encoding="utf-8")

    atomic_write_json(path, {"new": True})

    assert json.loads(path.read_text(encoding="utf-8")) == {"new": True}
    assert [p.name for p in tmp_path.iterdir()] == ["record.json"]


def test_failed_write_keeps_the_previous_file_and_cleans_up(tmp_path, monkeypatch):
    path = tmp_path / "record.json"
    path.write_text('{"old": true}\n', encoding="utf-8")

    def fail_replace(_source, _target):
        raise OSError("disk full")

    monkeypatch.setattr(json_files.os, "replace", fail_replace)

    with pytest.raises(OSError, match="disk full"):
        atomic_write_json(path, {"new": True})
    assert json.loads(path.read_text(encoding="utf-8")) == {"old": True}
    assert [p.name for p in tmp_path.iterdir()] == ["record.json"]


def test_unserializable_payload_raises_without_touching_the_file(tmp_path):
    path = tmp_path / "record.json"
    path.write_text('{"old": true}\n', encoding="utf-8")

    with pytest.raises(TypeError):
        atomic_write_json(path, {"bad": object()})
    assert json.loads(path.read_text(encoding="utf-8")) == {"old": True}
    assert [p.name for p in tmp_path.iterdir()] == ["record.json"]
