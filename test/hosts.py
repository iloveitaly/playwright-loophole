"""Manage the container-only hosts entry using python-hosts, including verification."""

import argparse
import socket

from python_hosts import Hosts, HostsEntry

HOSTNAME = "service.loophole.test"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["add", "remove"])
    args = parser.parse_args()
    hosts = Hosts(path="/etc/hosts")
    if args.action == "add":
        if hosts.exists(names=[HOSTNAME]):
            raise RuntimeError(f"Refusing to overwrite existing hosts entry: {HOSTNAME}")
        hosts.add(
            [HostsEntry(entry_type="ipv4", address="127.0.0.1", names=[HOSTNAME])],
            allow_address_duplication=True,
        )
        hosts.write()
        assert socket.gethostbyname(HOSTNAME) == "127.0.0.1"
    else:
        hosts.remove_all_matching(name=HOSTNAME)
        hosts.write()
        assert not Hosts(path="/etc/hosts").exists(names=[HOSTNAME])
    print(f"Hosts entry {args.action}: {HOSTNAME}", flush=True)


if __name__ == "__main__":
    main()
