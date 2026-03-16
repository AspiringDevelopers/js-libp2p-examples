from __future__ import annotations

from enum import Enum
from pathlib import Path

from rich.console import Console
import trio
import typer

from .node import NodeStartupInfo, start_node_once
from .phase2 import (
    DEFAULT_CHUNK_SIZE,
    download_file,
    resolve_manifest_by_file_hash,
    share_file,
)

app = typer.Typer(help="Lean py-libp2p MVP CLI (Phase 1)")
console = Console()


class DiscoveryMode(str, Enum):
    DHT = "dht"
    NON_DHT = "non-dht"
    HYBRID = "hybrid"


def _print_startup(info: NodeStartupInfo) -> None:
    console.print(f"[bold]Peer ID:[/bold] {info.peer_id}")
    console.print(f"[bold]Discovery mode:[/bold] {info.discovery_mode}")
    console.print("[bold]Listening multiaddrs:[/bold]")
    for addr in info.listen_addrs:
        console.print(f"  - {addr}")


async def _run_with_startup(
    mode: DiscoveryMode, port: int, hold_seconds: float
) -> None:
    startup = await start_node_once(
        discovery_mode=mode.value,
        port=port,
        hold_seconds=hold_seconds,
    )
    _print_startup(startup)


@app.command()
def share(
    file: Path = typer.Argument(..., exists=True, dir_okay=False, readable=True),
    mode: DiscoveryMode = typer.Option(DiscoveryMode.HYBRID, "--mode"),
    port: int = typer.Option(0, "--port", help="UDP port. 0 = auto"),
    chunk_size_mb: int = typer.Option(
        DEFAULT_CHUNK_SIZE // (1024 * 1024),
        "--chunk-size-mb",
        min=1,
        help="Chunk size for manifest chunk-CID calculation",
    ),
    hold_seconds: float = typer.Option(
        1.0, "--hold-seconds", help="How long to keep node alive after startup"
    ),
) -> None:
    """Phase 2 share: ingest file, create/persist manifest metadata."""
    trio.run(_run_with_startup, mode, port, hold_seconds)
    result = share_file(file, chunk_size=chunk_size_mb * 1024 * 1024)
    console.print(f"[green]shared[/green]: {file}")
    console.print(f"[bold]file_hash (sha256):[/bold] {result.file_hash}")
    console.print(f"[bold]root_cid:[/bold] {result.root_cid}")
    console.print(f"[bold]size:[/bold] {result.size_bytes} bytes")
    console.print(f"[bold]chunks:[/bold] {result.chunk_count}")
    console.print(f"[bold]manifest:[/bold] {result.manifest_path}")


@app.command()
def discover(
    file_hash: str = typer.Argument(...),
    mode: DiscoveryMode = typer.Option(DiscoveryMode.HYBRID, "--mode"),
    port: int = typer.Option(0, "--port", help="UDP port. 0 = auto"),
    hold_seconds: float = typer.Option(
        1.0, "--hold-seconds", help="How long to keep node alive after startup"
    ),
) -> None:
    """Phase 2 discover: resolve file_hash to manifest/provider metadata."""
    trio.run(_run_with_startup, mode, port, hold_seconds)
    try:
        manifest = resolve_manifest_by_file_hash(file_hash)
    except FileNotFoundError as exc:
        console.print(f"[red]discover failed:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    console.print(f"[green]discovered[/green]: {file_hash}")
    console.print(f"[bold]root_cid:[/bold] {manifest['root_cid']}")
    console.print(f"[bold]file_name:[/bold] {manifest['file_name']}")
    console.print(f"[bold]size:[/bold] {manifest['size_bytes']} bytes")
    console.print(f"[bold]source_path:[/bold] {manifest['source_path']}")


@app.command()
def download(
    file_hash: str = typer.Argument(...),
    mode: DiscoveryMode = typer.Option(DiscoveryMode.HYBRID, "--mode"),
    port: int = typer.Option(0, "--port", help="UDP port. 0 = auto"),
    output: Path | None = typer.Option(
        None, "--output", help="Output file path (default: mvp/data/downloads/<name>)"
    ),
    hold_seconds: float = typer.Option(
        1.0, "--hold-seconds", help="How long to keep node alive after startup"
    ),
) -> None:
    """Phase 2 download: resumable local transfer + integrity verification."""
    trio.run(_run_with_startup, mode, port, hold_seconds)
    try:
        result = download_file(file_hash=file_hash, destination=output)
    except (FileNotFoundError, ValueError) as exc:
        console.print(f"[red]download failed:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    console.print(f"[green]downloaded[/green]: {result.file_hash}")
    console.print(f"[bold]destination:[/bold] {result.destination}")
    console.print(f"[bold]resumed_from:[/bold] {result.resumed_from} bytes")
    console.print(f"[bold]bytes_written:[/bold] {result.bytes_written}")


def main() -> None:
    app()
