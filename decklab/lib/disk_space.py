"""Free disk space and the data folders' sizes (E11-S86), for `python -m decklab.db status`,
`python -m decklab.lib.homenet status` and the nightly task.

measure() asks each folder's disk how much is free (an injected disk-usage call, default
shutil.disk_usage) and walks each folder to add up its files, the walk capped by a file count
and a time budget. judge() turns a measurement into lines, each "ok" or "warn": one per disk
(two folders on one disk count the disk once) and one naming every folder's size.

The lines name each folder only by its fixed label (backups, Forge results, gauntlet, shops,
card data), never by its absolute path, and carry no error text (which may hold a path). A folder
that can't be read, or whose walk was cut short, has an unknown size, never zero; a folder that
isn't there yet is "none yet". Symbolic links and junctions are never followed or counted.

The warning level is config.json's optional "disk_space": {"warn_below_gb": N} (default 10 GB
free; the real level is set on the server PC). Standard library only.
"""
import os
import shutil
import stat
import time
from pathlib import Path

from decklab.lib import config, pathsetting

LABELS = ("backups", "Forge results", "gauntlet", "shops", "card data")
SETTING = "disk_space"
DEFAULT_WARN_GB = 10
GB = 1_000_000_000
MAX_ENTRIES = 250_000          # files and folders one label's walk may visit before giving up
MAX_SECONDS = 2.0              # and the time it may take
OK, WARN = "ok", "warn"

CANT_READ = "couldn't be read"
TOO_MANY = "too many files to count"
TOO_SLOW = "took too long to count"


def folders(settings=None):
    """[(label, [Path, ...])] for LABELS in order: the backups' staging folder (config.json's
    database.staging_dir, else decklab/data/backups), Forge's results, the gauntlet's catalogue
    and results, the shops' snapshots and the card data (Scryfall's bulk files and images).
    A staging_dir this PC can't use falls back to the default folder."""
    settings = config.load() if settings is None else settings
    data = Path(config.DATA)
    block = settings.get("database") if isinstance(settings, dict) else None
    staging = None
    if isinstance(block, dict):
        try:
            staging = pathsetting.normalise("database.staging_dir", block.get("staging_dir"))
        except ValueError:
            staging = None
    forge = data / "forge"
    return [("backups", [Path(staging) if staging else data / "backups"]),
            ("Forge results", [forge / "results"]),
            ("gauntlet", [data / "gauntlet", forge / "gauntlet"]),
            ("shops", [data / "shops"]),
            ("card data", [data / "scryfall", data / "images"])]


def warn_below(settings=None):
    """The free bytes under which a disk warns: config.json's disk_space.warn_below_gb when it's
    a positive number, else DEFAULT_WARN_GB."""
    settings = config.load() if settings is None else settings
    block = settings.get(SETTING) if isinstance(settings, dict) else None
    value = block.get("warn_below_gb") if isinstance(block, dict) else None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not value > 0:
        value = DEFAULT_WARN_GB
    return int(value * GB)


def _existing(path):
    """path, or its nearest ancestor that exists (where a folder not made yet would go)."""
    path = Path(path)
    for candidate in (path, *path.parents):
        try:
            if candidate.exists():
                return candidate
        except OSError:
            continue
    return path


def _device(path):
    return os.stat(path).st_dev


def _walk(root, budget, scandir=os.scandir):
    """(bytes, present, reason) for one folder: reason None when every file was counted.
    budget is a dict with "entries" left and a "deadline" (and "clock"), shared by one label."""
    try:
        first = scandir(root)
    except FileNotFoundError:
        return 0, False, None
    except OSError:
        return None, True, CANT_READ
    total, pending = 0, [first]
    try:
        while pending:
            with pending.pop() as entries:
                for entry in entries:
                    budget["entries"] -= 1
                    if budget["entries"] < 0:
                        return None, True, TOO_MANY
                    if budget["clock"]() > budget["deadline"]:
                        return None, True, TOO_SLOW
                    info = entry.stat(follow_symlinks=False)
                    if stat.S_ISLNK(info.st_mode) or getattr(entry, "is_junction", lambda: False)():
                        continue                    # never followed or counted
                    if stat.S_ISDIR(info.st_mode):
                        pending.append(scandir(entry.path))
                    elif stat.S_ISREG(info.st_mode):
                        total += info.st_size
    except OSError:
        return None, True, CANT_READ
    finally:
        for left in pending:
            try:
                left.close()
            except Exception:       # noqa: BLE001 (closing what the walk didn't reach)
                pass
    return total, True, None


def measure(folder_list=None, *, disk_usage=shutil.disk_usage, device=_device, scandir=os.scandir,
            clock=time.monotonic, max_entries=MAX_ENTRIES, max_seconds=MAX_SECONDS):
    """{"folders": [{"label", "bytes" (None: unknown), "present", "reason"}],
        "disks": [{"labels", "free", "total"}]} for folder_list (default folders()).
    Each label's walk has its own budget of max_entries and max_seconds. Disks are told apart
    by device (st_dev of the folder, or of its nearest existing parent); one whose device can't
    be read is told apart by that parent instead. A disk whose usage can't be read has free and
    total None."""
    folder_list = folders() if folder_list is None else folder_list
    out_folders, disks = [], {}
    for label, paths in folder_list:
        budget = {"entries": max_entries, "deadline": clock() + max_seconds, "clock": clock}
        size, present, reason = 0, False, None
        for path in paths:
            got, here, why = _walk(path, budget, scandir)
            present = present or here
            if got is None:
                size, reason = None, why
                break
            size += got
        for path in paths:          # every path's disk counts, even after a walk stopped
            anchor = _existing(path)
            try:
                key = ("device", device(anchor))
            except (OSError, ValueError):
                key = ("path", str(anchor))
            disk = disks.setdefault(key, {"labels": [], "anchor": anchor})
            if label not in disk["labels"]:
                disk["labels"].append(label)
        out_folders.append({"label": label, "bytes": size, "present": present, "reason": reason})
    out_disks = []
    for disk in disks.values():
        try:
            usage = disk_usage(str(disk["anchor"]))
            free, total = int(usage.free), int(usage.total)
        except (OSError, ValueError, AttributeError, TypeError):
            free = total = None
        out_disks.append({"labels": disk["labels"], "free": free, "total": total})
    return {"folders": out_folders, "disks": out_disks}


def size_text(n):
    """Bytes in decimal units: "512 B", "3.4 MB", "12.0 GB"."""
    if n < 1000:
        return f"{n} B"
    for unit in ("KB", "MB", "GB", "TB"):
        n /= 1000
        if n < 1000 or unit == "TB":
            return f"{n:.1f} {unit}"


def _names(labels):
    return labels[0] if len(labels) == 1 else ", ".join(labels[:-1]) + " and " + labels[-1]


def judge(measurement, warn_below_bytes=DEFAULT_WARN_GB * GB):
    """[{"level": "ok"|"warn", "text"}]: a Disk line per disk (warn under warn_below_bytes free,
    or when its free space is unknown), then one Data folders line."""
    out = []
    disks = measurement.get("disks") or []
    for disk in disks:
        name = "Disk" if len(disks) == 1 else f"Disk holding {_names(disk['labels'])}"
        free, total = disk.get("free"), disk.get("total")
        if free is None or not total:
            out.append({"level": WARN, "text": f"{name}: free space unknown (the disk couldn't be read)."})
            continue
        share = f"{free * 100 // total}%"
        if free < warn_below_bytes:
            out.append({"level": WARN, "text": f"{name}: only {size_text(free)} free of {size_text(total)} "
                        f"({share}), under the {size_text(warn_below_bytes)} warning level. Backups, Forge "
                        f"results and the card update need room: make space before the disk fills."})
        else:
            out.append({"level": OK, "text": f"{name}: {size_text(free)} free of {size_text(total)} ({share})."})
    parts = []
    for folder in measurement.get("folders") or []:
        if folder.get("bytes") is None:
            parts.append(f"{folder['label']} unknown ({folder.get('reason') or CANT_READ})")
        elif not folder.get("present"):
            parts.append(f"{folder['label']} none yet")
        else:
            parts.append(f"{folder['label']} {size_text(folder['bytes'])}")
    if parts:
        out.append({"level": OK, "text": "Data folders: " + ", ".join(parts) + "."})
    return out


def report(settings=None, **measure_options):
    """judge(measure(folders(settings)), warn_below(settings)): the lines status shows. Never
    raises: a failure is one warn line naming only its exception type."""
    try:
        settings = config.load() if settings is None else settings
    except (OSError, ValueError, TypeError):
        settings = {}
    try:
        return judge(measure(folders(settings), **measure_options), warn_below(settings))
    except Exception as e:          # noqa: BLE001 (one line, never the whole status)
        return [{"level": WARN, "text": f"Disk: couldn't check free space ({type(e).__name__})."}]
