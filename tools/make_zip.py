import argparse
import sys
import zipfile
from pathlib import Path


def make_zip(src_dir: Path, dest_zip: Path) -> None:
    if not src_dir.exists() or not src_dir.is_dir():
        raise FileNotFoundError(f"Source directory not found: {src_dir}")

    dest_zip.parent.mkdir(parents=True, exist_ok=True)
    if dest_zip.exists():
        dest_zip.unlink()

    with zipfile.ZipFile(dest_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for p in src_dir.rglob("*"):
            if not p.is_file():
                continue
            arcname = p.relative_to(src_dir).as_posix()
            zf.write(p, arcname)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("src_dir")
    parser.add_argument("dest_zip")
    args = parser.parse_args()

    try:
        make_zip(Path(args.src_dir), Path(args.dest_zip))
        return 0
    except Exception as e:
        print(str(e), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
