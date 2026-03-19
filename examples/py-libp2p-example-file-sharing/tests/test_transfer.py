from __future__ import annotations

from pathlib import Path

from mvp_app.transfer import download_file, resolve_manifest_by_file_hash, share_file


def test_share_and_download_roundtrip(tmp_path: Path, monkeypatch) -> None:
    data_dir = tmp_path / "appdata"
    monkeypatch.setenv("MVP_DATA_DIR", str(data_dir))

    source = tmp_path / "source.bin"
    payload = (b"lean-libp2p-transfer-" * 1024) + b"done"
    source.write_bytes(payload)

    share = share_file(source, chunk_size=128 * 1024)
    manifest = resolve_manifest_by_file_hash(share.file_hash)

    assert manifest["size_bytes"] == len(payload)
    assert manifest["file_sha256"] == share.file_hash
    assert manifest["root_cid"] == share.root_cid

    out = tmp_path / "download.bin"
    result = download_file(share.file_hash, destination=out)

    assert result.file_hash == share.file_hash
    assert out.read_bytes() == payload
    assert not out.with_suffix(".bin.part").exists()
