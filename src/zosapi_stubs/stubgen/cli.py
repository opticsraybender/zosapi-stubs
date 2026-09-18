"""Command-line entry point for ``zosapi-stubgen``.

Installed alongside the prebuilt ``ZOSAPI-stubs`` package, this command lets a
user *rebuild* the stubs in place after upgrading OpticStudio — no source
checkout required:

    zosapi-stubgen                       # rebuild in place using the default DLL dir
    zosapi-stubgen --dll-dir "D:\\Zemax"  # custom install location
    zosapi-stubgen -o ./typings           # write somewhere else instead of in place
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .generator import STUB_PACKAGE_SUFFIX, generate

DEFAULT_DLL_DIR = Path(r"C:\Program Files\Zemax OpticStudio")


def _installed_stub_root() -> Path | None:
    """Return the site-packages dir that contains the installed ``ZOSAPI-stubs``."""
    # The stub package dir is literally "ZOSAPI-stubs" (not importable), so locate
    # it by scanning this package's installation root.
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / ("ZOSAPI" + STUB_PACKAGE_SUFFIX)
        if candidate.is_dir():
            return parent
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="zosapi-stubgen",
        description="Rebuild ZOS-API type stubs by reflecting over the OpticStudio DLLs.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--dll-dir", type=Path, default=DEFAULT_DLL_DIR, metavar="DIR",
        help="Directory containing ZOSAPI.dll / ZOSAPI_Interfaces.dll (+ their .xml).",
    )
    parser.add_argument(
        "--output-dir", "-o", type=Path, default=None, metavar="DIR",
        help="Where to write the ZOSAPI-stubs package "
             "(default: rebuild in place where this package is installed).",
    )
    args = parser.parse_args(argv)

    if not (args.dll_dir / "ZOSAPI.dll").is_file():
        parser.error(f"ZOSAPI.dll not found in {args.dll_dir!s}. Pass --dll-dir.")

    output_dir = args.output_dir
    if output_dir is None:
        output_dir = _installed_stub_root()
        if output_dir is None:
            parser.error(
                "Could not locate the installed ZOSAPI-stubs package; "
                "pass --output-dir to choose where to write."
            )
        print(f"Rebuilding stubs in place: {output_dir}")

    try:
        import clr  # noqa: F401
    except ImportError:
        parser.error(
            "pythonnet is required to read the DLLs. Install it with:\n"
            "  pip install pythonnet"
        )

    generate(args.dll_dir, output_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
