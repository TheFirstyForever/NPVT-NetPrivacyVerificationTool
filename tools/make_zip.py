import argparse
import sys
import zipfile
from pathlib import Path


def make_zip(src_dir: Path, dest_zip: Path, *, compresslevel: int, progress_every: int) -> None:
    if not src_dir.exists() or not src_dir.is_dir():
        raise FileNotFoundError(f"Source directory not found: {src_dir}")

    dest_zip.parent.mkdir(parents=True, exist_ok=True)
    if dest_zip.exists():
        dest_zip.unlink()

    files = [p for p in src_dir.rglob("*") if p.is_file()]
    total = len(files)
    print(f"[make_zip] src={src_dir}")
    print(f"[make_zip] dest={dest_zip}")
    print(f"[make_zip] files={total} compresslevel={compresslevel}")

    with zipfile.ZipFile(
        dest_zip,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=compresslevel,
    ) as zf:
        for i, p in enumerate(files, start=1):
            arcname = p.relative_to(src_dir).as_posix()
            zf.write(p, arcname)
            if progress_every > 0 and (i % progress_every == 0):
                print(f"[make_zip] {i}/{total}...")

    size = dest_zip.stat().st_size
    print(f"[make_zip] done size={size} bytes")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("src_dir")
    parser.add_argument("dest_zip")
    parser.add_argument("--compresslevel", type=int, default=6)
    parser.add_argument("--progress-every", type=int, default=200)
    args = parser.parse_args()

    try:
        make_zip(
            Path(args.src_dir),
            Path(args.dest_zip),
            compresslevel=args.compresslevel,
            progress_every=args.progress_every,
        )
        return 0
    except Exception as e:
        print(f"[make_zip] ERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
