"""Discover stable upstream image variants; emit a GitHub Actions matrix."""
import argparse
import json
import os
import re
from urllib.request import urlopen

STABLE_TAG = re.compile(r"v(\d+)\.(\d+)\.(\d+)(?:-(?:noble|jammy|resolute))?")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", default="", help="Release such as v1.64.1; empty selects latest stable")
    args = parser.parse_args()
    if args.version and not re.fullmatch(r"v\d+\.\d+\.\d+", args.version):
        parser.error("version must look like v1.64.1 (no distro suffix or prerelease)")
    with urlopen("https://mcr.microsoft.com/v2/playwright/tags/list", timeout=60) as response:
        tags = json.load(response)["tags"]
    stable = {tag: tuple(map(int, match.groups())) for tag in tags if (match := STABLE_TAG.fullmatch(tag))}
    if not stable:
        raise RuntimeError("Upstream registry returned no supported stable tags")
    version = args.version or "v" + ".".join(map(str, max(stable.values())))
    selected = sorted(tag for tag in stable if tag == version or tag.startswith(version + "-"))
    if not selected:
        raise RuntimeError(f"Upstream has no supported tags for {version}")
    matrix = json.dumps({"tag": selected}, separators=(",", ":"))
    print(matrix)
    if output := os.environ.get("GITHUB_OUTPUT"):
        with open(output, "a") as stream:
            stream.write(f"matrix={matrix}\n")
            stream.write(f"version={version}\n")


if __name__ == "__main__":
    main()
