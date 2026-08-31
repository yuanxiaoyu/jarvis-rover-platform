def test_no_audio_files_are_created_by_import(tmp_path, monkeypatch):
    import rover_voice.audio  # noqa: F401
    assert list(tmp_path.iterdir()) == []
