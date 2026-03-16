from __future__ import annotations

from dataclasses import dataclass
import secrets

from multiaddr import Multiaddr
import trio

from libp2p import new_host
from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.utils.address_validation import find_free_port, get_available_interfaces


@dataclass(frozen=True)
class NodeStartupInfo:
    peer_id: str
    listen_addrs: list[str]
    discovery_mode: str


def _to_quic_v1(addr: Multiaddr) -> Multiaddr:
    addr_str = str(addr)
    if "/tcp/" in addr_str:
        addr_str = addr_str.replace("/tcp/", "/udp/")
    if addr_str.endswith("/quic"):
        addr_str = f"{addr_str[:-5]}/quic-v1"
    elif "/quic-v1" not in addr_str:
        addr_str = f"{addr_str}/quic-v1"
    return Multiaddr(addr_str)


def build_quic_listen_addrs(port: int) -> tuple[int, list[Multiaddr]]:
    selected_port = port if port > 0 else find_free_port()
    raw_addrs = get_available_interfaces(selected_port, protocol="udp")
    quic_addrs = [_to_quic_v1(addr) for addr in raw_addrs]
    return selected_port, quic_addrs


async def start_node_once(
    *,
    discovery_mode: str,
    port: int = 0,
    hold_seconds: float = 1.0,
) -> NodeStartupInfo:
    secret = secrets.token_bytes(32)
    host = new_host(key_pair=create_new_key_pair(secret), enable_quic=True)
    _, listen_addrs = build_quic_listen_addrs(port)

    async with host.run(listen_addrs=listen_addrs):
        info = NodeStartupInfo(
            peer_id=host.get_id().to_string(),
            listen_addrs=[str(addr) for addr in host.get_addrs()],
            discovery_mode=discovery_mode,
        )
        if hold_seconds > 0:
            await trio.sleep(hold_seconds)
        return info

