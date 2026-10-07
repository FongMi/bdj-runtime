"""Separate OpenJDK's debug symbols from the downloadable BD-J runtime."""

import argparse
import pathlib
import zipfile


def package_runtime(source, runtime, symbols):
    with zipfile.ZipFile(source) as image:
        with (
            zipfile.ZipFile(runtime, "x") as runtime_zip,
            zipfile.ZipFile(symbols, "x") as symbols_zip,
        ):
            for entry in image.infolist():
                output = symbols_zip if entry.filename.endswith(".diz") else runtime_zip
                output.writestr(
                    entry, image.read(entry), compress_type=entry.compress_type, compresslevel=6
                )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=pathlib.Path, required=True)
    parser.add_argument("--runtime", type=pathlib.Path, required=True)
    parser.add_argument("--symbols", type=pathlib.Path, required=True)
    args = parser.parse_args()
    package_runtime(args.source, args.runtime, args.symbols)


if __name__ == "__main__":
    main()
