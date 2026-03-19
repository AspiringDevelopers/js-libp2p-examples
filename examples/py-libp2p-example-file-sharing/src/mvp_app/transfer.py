from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
from typing import Any

from libp2p.bitswap.cid import cid_to_text, compute_cid_v1, verify_cid

APP_VERSION = 1
DEFAULT_CHUNK_SIZE = 1024 * 1024


def _mvp_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _data_root() -> Path:
    custom = os.getenv("MVP_DATA_DIR")
    if custom:
        return Path(custom).resolve()
    return _mvp_root() / "data"


def _catalog_root() -> Path:
    return _data_root() / "catalog"


def _manifests_dir() -> Path:
    return _catalog_root() / "manifests"


def _index_path() -> Path:
    return _catalog_root() / "index_by_sha256.json"


def _downloads_dir() -> Path:
    return _data_root() / "downloads"


def _ensure_layout() -> None:
    _data_root().mkdir(parents=True, exist_ok=True)
    _catalog_root().mkdir(parents=True, exist_ok=True)
    _manifests_dir().mkdir(parents=True, exist_ok=True)
    _downloads_dir().mkdir(parents=True, exist_ok=True)


def _sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fp:
        while True:
            chunk = fp.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _compute_chunk_cids(path: Path, chunk_size: int) -> list[str]:
    chunk_cids: list[str] = []
    with path.open("rb") as fp:
        while True:
            chunk = fp.read(chunk_size)
            if not chunk:
                break
            chunk_cid = cid_to_text(compute_cid_v1(chunk))
            chunk_cids.append(chunk_cid)
    return chunk_cids


def _load_index() -> dict[str, str]:
    index_file = _index_path()
    if not index_file.exists():
        return {}
    with index_file.open("r", encoding="utf-8") as fp:
        data: dict[str, str] = json.load(fp)
    return data


def _save_index(index: dict[str, str]) -> None:
    with _index_path().open("w", encoding="utf-8") as fp:
        json.dump(index, fp, indent=2, sort_keys=True)


def _manifest_path(root_cid: str) -> Path:
    return _manifests_dir() / f"{root_cid}.json"


def _write_manifest(manifest: dict[str, Any]) -> Path:
    root_cid = manifest["root_cid"]
    path = _manifest_path(root_cid)
    with path.open("w", encoding="utf-8") as fp:
        json.dump(manifest, fp, indent=2, sort_keys=True)
    return path


def _build_manifest(file_path: Path, chunk_size: int) -> dict[str, Any]:
    file_size = file_path.stat().st_size
    file_sha256 = _sha256_file(file_path)
    chunk_cids = _compute_chunk_cids(file_path, chunk_size)

    manifest_core: dict[str, Any] = {
        "app_version": APP_VERSION,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "file_name": file_path.name,
        "source_path": str(file_path.resolve()),
        "size_bytes": file_size,
        "file_sha256": file_sha256,
        "chunk_size_bytes": chunk_size,
        "chunk_count": len(chunk_cids),
        "chunk_cids": chunk_cids,
    }
    canonical = json.dumps(manifest_core, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    root_cid = cid_to_text(compute_cid_v1(canonical))
    manifest_core["root_cid"] = root_cid
    return manifest_core


@dataclass(frozen=True)
class ShareResult:
    file_hash: str
    root_cid: str
    manifest_path: Path
    size_bytes: int
    chunk_count: int


def share_file(file_path: Path, chunk_size: int = DEFAULT_CHUNK_SIZE) -> ShareResult:
    _ensure_layout()
    manifest = _build_manifest(file_path=file_path, chunk_size=chunk_size)
    manifest_path = _write_manifest(manifest)

    index = _load_index()
    file_hash = manifest["file_sha256"]
    index[file_hash] = manifest["root_cid"]
    _save_index(index)

    return ShareResult(
        file_hash=file_hash,
        root_cid=manifest["root_cid"],
        manifest_path=manifest_path,
        size_bytes=manifest["size_bytes"],
        chunk_count=manifest["chunk_count"],
    )


def resolve_manifest_by_file_hash(file_hash: str) -> dict[str, Any]:
    _ensure_layout()
    root_cid = _load_index().get(file_hash)
    if not root_cid:
        raise FileNotFoundError(f"unknown file_hash: {file_hash}")

    path = _manifest_path(root_cid)
    if not path.exists():
        raise FileNotFoundError(f"manifest missing for root_cid={root_cid}")
    with path.open("r", encoding="utf-8") as fp:
        manifest: dict[str, Any] = json.load(fp)
    return manifest


def verify_file_against_manifest(file_path: Path, manifest: dict[str, Any]) -> None:
    if not file_path.exists():
        raise FileNotFoundError(f"file missing: {file_path}")

    expected_size = int(manifest["size_bytes"])
    if file_path.stat().st_size != expected_size:
        raise ValueError(
            f"size mismatch: got={file_path.stat().st_size}, expected={expected_size}"
        )

    expected_sha = str(manifest["file_sha256"])
    actual_sha = _sha256_file(file_path)
    if actual_sha != expected_sha:
        raise ValueError(f"sha256 mismatch: got={actual_sha}, expected={expected_sha}")

    chunk_size = int(manifest["chunk_size_bytes"])
    expected_chunk_cids = list(manifest["chunk_cids"])
    with file_path.open("rb") as fp:
        for idx, expected_cid in enumerate(expected_chunk_cids):
            chunk = fp.read(chunk_size)
            if not chunk:
                raise ValueError(f"missing chunk index={idx}")
            if not verify_cid(expected_cid, chunk):
                got = cid_to_text(compute_cid_v1(chunk))
                raise ValueError(
                    f"chunk cid mismatch index={idx}: got={got}, expected={expected_cid}"
                )


@dataclass(frozen=True)
class DownloadResult:
    destination: Path
    bytes_written: int
    resumed_from: int
    file_hash: str


def download_file(file_hash: str, destination: Path | None = None) -> DownloadResult:
    _ensure_layout()
    manifest = resolve_manifest_by_file_hash(file_hash)
    source_path = Path(str(manifest["source_path"]))
    if not source_path.exists():
        raise FileNotFoundError(
            f"source file is unavailable for now: {source_path} "
            "(Phase 2 uses local known-peer source path)"
        )

    dest = destination or (_downloads_dir() / str(manifest["file_name"]))
    dest.parent.mkdir(parents=True, exist_ok=True)
    temp_dest = dest.with_suffix(dest.suffix + ".part")

    expected_size = int(manifest["size_bytes"])
    resumed_from = temp_dest.stat().st_size if temp_dest.exists() else 0
    if resumed_from > expected_size:
        temp_dest.unlink(missing_ok=True)
        resumed_from = 0

    if resumed_from < expected_size:
        with source_path.open("rb") as src, temp_dest.open("ab") as out:
            src.seek(resumed_from)
            shutil.copyfileobj(src, out, length=1024 * 1024)

    final_size = temp_dest.stat().st_size if temp_dest.exists() else 0
    if final_size != expected_size:
        raise ValueError(f"incomplete transfer: got={final_size}, expected={expected_size}")

    verify_file_against_manifest(temp_dest, manifest)
    temp_dest.replace(dest)

    return DownloadResult(
        destination=dest,
        bytes_written=expected_size - resumed_from,
        resumed_from=resumed_from,
        file_hash=file_hash,
    )
