"discover stable upstream image variants; emit a github actions matrix"

import argparse
import json
import os
import re
from pathlib import Path
from urllib.request import urlopen

PLAYWRIGHT_TAGS_URL = "https://mcr.microsoft.com/v2/playwright/tags/list"
TIMEOUT_SECONDS = 60
ARCHITECTURES = ("amd64", "arm64")

STABLE_TAG_PATTERN = re.compile(
    r"""
    v
    (\d+)                           # major release version
    \.
    (\d+)                           # minor release version
    \.
    (\d+)                           # patch release version
    (?:-(?:noble|jammy|resolute))?  # optional ubuntu distribution suffix
    """,
    re.VERBOSE,
)

VERSION_ARG_PATTERN = re.compile(
    r"""
    v
    \d+                             # major release version
    \.
    \d+                             # minor release version
    \.
    \d+                             # patch release version
    """,
    re.VERBOSE,
)


def expand_arch_tags(tag: str) -> list[str]:
    "expand a base tag with architecture-specific suffixes"

    return [tag, *(f"{tag}-{arch}" for arch in ARCHITECTURES)]


def published_tags(selected: list[str], version: str, is_latest: bool) -> list[str]:
    "build the list of docker image tags published for the selected version"

    tags: list[str] = []
    for tag in selected:
        tags.extend(expand_arch_tags(tag))

        if not is_latest:
            continue

        if tag == version:
            tags.extend(expand_arch_tags("latest"))
            continue

        if tag == f"{version}-noble":
            tags.extend(expand_arch_tags("noble"))

    return tags


def fetch_upstream_tags() -> list[str]:
    "fetch published playwright tags from the upstream container registry"

    with urlopen(PLAYWRIGHT_TAGS_URL, timeout=TIMEOUT_SECONDS) as response:
        payload = json.load(response)

    return payload["tags"]


def extract_stable_tags(tags: list[str]) -> dict[str, tuple[int, int, int]]:
    "parse tags matching the stable release pattern into version tuples"

    stable: dict[str, tuple[int, int, int]] = {}
    for tag in tags:
        match = STABLE_TAG_PATTERN.fullmatch(tag)
        if not match:
            continue

        stable[tag] = (int(match.group(1)), int(match.group(2)), int(match.group(3)))

    if not stable:
        raise RuntimeError("Upstream registry returned no supported stable tags")

    return stable


def resolve_version_tags(
    stable: dict[str, tuple[int, int, int]], requested_version: str
) -> tuple[list[str], str, bool]:
    "resolve image tags for requested or latest stable version"

    latest_numbers = max(stable.values())
    latest_version = f"v{latest_numbers[0]}.{latest_numbers[1]}.{latest_numbers[2]}"

    version = requested_version or latest_version
    is_latest = version == latest_version

    selected = sorted(tag for tag in stable if tag == version or tag.startswith(f"{version}-"))
    if not selected:
        raise RuntimeError(f"Upstream has no supported tags for {version}")

    return selected, version, is_latest


def write_github_output(output_path: Path, matrix: str, version: str, is_latest: bool) -> None:
    "append matrix, version, and latest flag to github actions step output"

    output_content = f"matrix={matrix}\nversion={version}\nis_latest={str(is_latest).lower()}\n"
    with output_path.open("a", encoding="utf-8") as stream:
        stream.write(output_content)


def parse_arguments() -> argparse.Namespace:
    "parse command line arguments for version selection and output formatting"

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--version", default="", help="Release such as v1.64.1; empty selects latest stable"
    )
    parser.add_argument(
        "--list-published",
        action="store_true",
        help="Print the list of tags that will be published to GHCR",
    )

    args = parser.parse_args()
    if args.version and not VERSION_ARG_PATTERN.fullmatch(args.version):
        parser.error("version must look like v1.64.1 (no distro suffix or prerelease)")

    return args


def main() -> None:
    "discover upstream tags and output matrix or published tag list"

    args = parse_arguments()
    tags = fetch_upstream_tags()
    stable = extract_stable_tags(tags)
    selected, version, is_latest = resolve_version_tags(stable, args.version)

    if args.list_published:
        for tag in published_tags(selected, version, is_latest):
            print(tag)

        return

    matrix = json.dumps({"tag": selected}, separators=(",", ":"))
    print(matrix)

    github_output = os.environ.get("GITHUB_OUTPUT")
    if not github_output:
        return

    write_github_output(Path(github_output), matrix, version, is_latest)


if __name__ == "__main__":
    main()
