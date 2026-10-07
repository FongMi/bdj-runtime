"""Fetch and verify the immutable source inputs preserved in this repository's release."""

import argparse
import hashlib
import json
import pathlib
import re
import urllib.request


def verify(path, source):
    if path.stat().st_size != source["size"]:
        raise ValueError("Source size mismatch: " + source["asset"])
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    if digest.hexdigest() != source["sha256"]:
        raise ValueError("Source SHA-256 mismatch: " + source["asset"])


def fetch(manifest, cache, verify_only=False):
    release = manifest["release"]
    if release["repository"] != "FongMi/bdj-runtime":
        raise ValueError("Sources must come from the preserved repository")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", release["tag"]):
        raise ValueError("Invalid source release tag")
    cache.mkdir(parents=True, exist_ok=True)
    for source in manifest["sources"].values():
        asset = source["asset"]
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", asset):
            raise ValueError("Invalid source asset name")
        path = cache / asset
        if path.exists():
            verify(path, source)
            print("Verified " + asset)
            continue
        if verify_only:
            raise FileNotFoundError(path)
        url = source.get("url")
        if url is not None:
            if url != "https://dl.google.com/android/repository/android-ndk-r10e-linux-x86_64.zip":
                raise ValueError("Only the official pinned NDK toolchain may use an external URL")
        else:
            url = "https://github.com/{repository}/releases/download/{tag}/{asset}".format(
                asset=asset, **release
            )
        temporary = path.with_suffix(path.suffix + ".partial")
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "BDJ-runtime-source-builder"})
            with urllib.request.urlopen(request, timeout=120) as response, temporary.open("xb") as out:
                while block := response.read(1024 * 1024):
                    out.write(block)
            verify(temporary, source)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
        print("Fetched and verified " + asset)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=pathlib.Path, required=True)
    parser.add_argument("--manifest", type=pathlib.Path,
                        default=pathlib.Path(__file__).resolve().parents[1] / "sources.json")
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    fetch(json.loads(args.manifest.read_text(encoding="utf-8")), args.cache, args.verify_only)


if __name__ == "__main__":
    main()
