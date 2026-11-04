"""Build a Deck Lab release zip, its SHA-256 and its version manifest (E11-S49).

    python scripts/make_release.py VERSION [--ref REF] [--out DIR]

VERSION is like 1.2.0 (a leading v is dropped). The zip holds the files git tracks at REF
(HEAD by default), under a folder decklab-VERSION/, so nothing gitignored (config.json, the
data cache, magic/, pokemon/, a .venv) can reach it, plus decklab/release.json, the manifest an
install without git reads its version from (decklab/lib/build.py):

    {"version", "commit", "runtime", "web", "migrations", "built_at"}

runtime and web are build.py's fingerprints of the shipped files, so the running server can
tell when a release's files were changed afterwards; migrations are the database migrations it
holds; built_at is REF's commit time. Every zip entry carries that time too, so the same REF
and VERSION make the same zip byte for byte. Written to DIR (dist/ by default):
decklab-VERSION.zip, decklab-VERSION.zip.sha256 (sha256sum's format) and decklab-VERSION.json
(the manifest again, for reading without unzipping).

The release workflow (.github/workflows/release.yml) runs this on a version tag and attaches the
files to a draft GitHub release, which Matt publishes. Exit codes: 0 written, 1 refused.
"""
import argparse
import hashlib
import io
import json
import re
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from decklab.lib import build  # noqa: E402

VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z][0-9A-Za-z.-]{0,30})?\Z")
LEFT_OUT = (".github/",)         # CI's own files: no use to an install


def _git(*args, raw=False):
    done = subprocess.run(["git", *args], cwd=REPO, capture_output=True, check=True)
    return done.stdout if raw else done.stdout.decode("utf-8").strip()


def _files(ref):
    """{path: (bytes, mode)} of the files git tracks at ref (git archive's tar, never the working tree)."""
    data = _git("archive", "--format=tar", ref, raw=True)
    out = {}
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        for member in tar.getmembers():
            if member.isfile() and not member.name.startswith(LEFT_OUT):
                out[member.name] = (tar.extractfile(member).read(), member.mode)
    return out


def manifest(version, commit, files, built_at):
    """The release manifest of files ({path: (bytes, mode)}), fingerprinted as build.py does."""
    with tempfile.TemporaryDirectory(prefix="decklab-release-") as folder:
        root = Path(folder)
        for name, (data, _) in files.items():
            if name.startswith("decklab/"):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
        fingerprints, _ = build._fingerprints(root)
    migrations = sorted(Path(name).name for name in files
                        if name.startswith("decklab/db/migrations/") and name.endswith(".sql"))
    return {"version": version, "commit": commit, "runtime": fingerprints["runtime"], "web": fingerprints["web"],
            "migrations": migrations, "built_at": built_at}


def write_zip(path, version, files, info, moment):
    """The zip: every file under decklab-VERSION/, with release.json added, in name order, all at moment."""
    stamp = moment.timetuple()[:6]
    folder = f"decklab-{version}/"
    entries = dict(files)
    entries[build.MANIFEST.as_posix()] = ((json.dumps(info, indent=1) + "\n").encode("utf-8"), 0o644)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(entries):
            data, mode = entries[name]
            item = zipfile.ZipInfo(folder + name, date_time=stamp)
            item.compress_type = zipfile.ZIP_DEFLATED
            item.external_attr = ((mode & 0o777) | 0o100000) << 16
            archive.writestr(item, data)


def make(version, ref="HEAD", out=None):
    """Write the three files; returns their paths. Raises ValueError for a bad version."""
    version = version[1:] if version.startswith("v") else version
    if not VERSION.fullmatch(version):
        raise ValueError(f"{version!r} isn't a release version like 1.2.0")
    commit = _git("rev-parse", "--verify", f"{ref}^{{commit}}")
    moment = datetime.fromtimestamp(int(_git("show", "-s", "--format=%ct", commit)), timezone.utc)
    files = _files(commit)
    if build.MANIFEST.as_posix() in files:
        raise ValueError(f"{build.MANIFEST.as_posix()} is tracked by git; it must only be made here")
    info = manifest(version, commit, files, moment.isoformat(timespec="seconds"))
    out = Path(out or REPO / "dist")
    out.mkdir(parents=True, exist_ok=True)
    archive = out / f"decklab-{version}.zip"
    write_zip(archive, version, files, info, moment)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    checksum = out / f"{archive.name}.sha256"
    checksum.write_text(f"{digest}  {archive.name}\n", encoding="utf-8", newline="\n")
    listed = out / f"decklab-{version}.json"
    listed.write_text(json.dumps(info, indent=1) + "\n", encoding="utf-8", newline="\n")
    return archive, checksum, listed


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build a Deck Lab release zip, its SHA-256 and its manifest.")
    parser.add_argument("version", help="the release version, such as 1.2.0 (a leading v is dropped)")
    parser.add_argument("--ref", default="HEAD", help="the commit or tag to package (default HEAD)")
    parser.add_argument("--out", help="the folder to write to (default dist/)")
    args = parser.parse_args(argv)
    try:
        written = make(args.version, args.ref, args.out)
    except (ValueError, subprocess.CalledProcessError) as error:
        print(f"Refused: {error}", file=sys.stderr)
        return 1
    for path in written:
        print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
