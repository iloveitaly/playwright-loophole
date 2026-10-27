"manage container hosts entry with verification"

import argparse
import socket
from pathlib import Path

from python_hosts import Hosts, HostsEntry

ETC_HOSTS = Path("/etc/hosts")
HOSTNAME = "service.loophole.test"
LOOPBACK_IP = "127.0.0.1"
ACTION_ADD = "add"
ACTION_REMOVE = "remove"
ENTRY_TYPE_IPV4 = "ipv4"


def add_hosts_entry() -> None:
    hosts = Hosts(path=ETC_HOSTS)
    assert not hosts.exists(names=[HOSTNAME])

    hosts.add(
        [HostsEntry(entry_type=ENTRY_TYPE_IPV4, address=LOOPBACK_IP, names=[HOSTNAME])],
        allow_address_duplication=True,
    )
    hosts.write()

    assert socket.gethostbyname(HOSTNAME) == LOOPBACK_IP


def remove_hosts_entry() -> None:
    hosts = Hosts(path=ETC_HOSTS)
    hosts.remove_all_matching(name=HOSTNAME)
    hosts.write()

    assert not Hosts(path=ETC_HOSTS).exists(names=[HOSTNAME])


def update_hosts(action: str) -> None:
    if action == ACTION_ADD:
        add_hosts_entry()
        return

    remove_hosts_entry()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=[ACTION_ADD, ACTION_REMOVE])
    args = parser.parse_args()

    update_hosts(args.action)
    print(f"Hosts entry {args.action}: {HOSTNAME}", flush=True)


if __name__ == "__main__":
    main()
