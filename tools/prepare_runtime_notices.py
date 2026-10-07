"""Bundle original dependency notices and source access with a BD-J runtime."""

import argparse
import json
import pathlib
import re

FREETYPE_NOTICES = (
    "docs/LICENSE.TXT",
    "docs/FTL.TXT",
    "docs/GPLv2.TXT",
    "src/bdf/README",
    "src/pcf/README",
    "src/base/fthash.c",
    "src/gzip/zlib.h",
)
PATCH_NOTICES = (
    "jdk8u_android.diff",
    "jdk8u_android_main.diff",
    "ICU57-LICENSE.txt",
    "SOURCE-NOTICE.txt",
)
IMAGE_NOTICES = (
    "LICENSE",
    "ASSEMBLY_EXCEPTION",
    "THIRD_PARTY_README",
    "lib/fonts/DEJAVU-LICENSE.txt",
    "provenance.json",
)


def prepare_notices(image, repo_root, libffi_source, freetype_source, patches):
    """Validate all inputs before adding documentation; leave runtime bytes alone."""
    if not image.is_dir():
        raise FileNotFoundError(image)
    for name in IMAGE_NOTICES:
        if not (image / name).read_bytes():
            raise ValueError("Empty runtime notice: " + name)
    inputs = {
        "third-party/libffi/LICENSE": libffi_source / "LICENSE",
        "SOURCE-NOTICE.md": repo_root / "SOURCE-NOTICE.md",
        "sources.json": repo_root / "sources.json",
    }
    inputs.update({"third-party/freetype/" + name: freetype_source / name
                   for name in FREETYPE_NOTICES})
    inputs.update({"third-party/android-port/" + name: patches / name
                   for name in PATCH_NOTICES})
    files = {}
    for destination, source in inputs.items():
        data = source.read_bytes()
        if not data:
            raise ValueError("Empty source notice: " + str(source))
        files[destination] = data
    manifest = json.loads(files["sources.json"])
    provenance = json.loads((image / "provenance.json").read_bytes())
    if (provenance["sources"] != manifest["sources"]
            or provenance["sourceRelease"] != manifest["release"]):
        raise ValueError("Runtime provenance and preserved source manifest differ")
    commit = provenance["recipeCommit"]
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("Expected a complete recipe commit SHA")
    repository = manifest["release"]["repository"]
    tag = manifest["release"]["tag"]
    files["SOURCE-AVAILABILITY.txt"] = (
        "Complete corresponding sources for this runtime are available at:\n"
        f"https://github.com/{repository}/releases/tag/{tag}\n\n"
        "Exact build recipe and local source modifications:\n"
        f"https://github.com/{repository}/archive/{commit}.zip\n\n"
        "sources.json identifies preserved archives by size and SHA-256.\n"
        "provenance.json identifies this runtime's original build recipe commit.\n"
        "SOURCE-NOTICE.md describes the original component licenses.\n"
        "The preserved OpenJDK source, Android patches, local adaptations and\n"
        "build scripts together form the corresponding source for the JVM.\n"
    ).encode("utf-8")
    for name, data in sorted(files.items()):
        destination = image / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", type=pathlib.Path, required=True)
    parser.add_argument("--repo-root", type=pathlib.Path, required=True)
    parser.add_argument("--libffi-source", type=pathlib.Path, required=True)
    parser.add_argument("--freetype-source", type=pathlib.Path, required=True)
    parser.add_argument("--patches", type=pathlib.Path, required=True)
    args = parser.parse_args()
    prepare_notices(
        args.image, args.repo_root, args.libffi_source, args.freetype_source, args.patches
    )
    print("Bundled original dependency notices and complete source access")


if __name__ == "__main__":
    main()
