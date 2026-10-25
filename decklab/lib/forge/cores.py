"""The PC's physical cores, for pinning Forge's processes (simulation wave 2, the report's
R01b): slot k of the PC's budget (slots.py) is core k, the cores ordered V-Cache CCD first
(the largest L3 first, then by first logical CPU), each core both of its logical CPUs. A
computing warm worker is pinned to its slot's core (pool.py), and so is the warm-equivalence
check's worker (servecheck.py), so the check plays its games the way the pool does.

    core_masks()        [the affinity mask of core k, for k = 0, 1, ...], read once from
                        GetLogicalProcessorInformationEx (RelationProcessorCore and
                        RelationCache L3); [] when the topology can't be read or is odd
                        (SMT off, a core in more than one processor group, a core outside
                        every L3...), logged once
    mask_for(slot)      core_masks()[slot], or None (no such core, or no topology)
    pin(pid, slot)      SetProcessAffinityMask of process pid to mask_for(slot): True when
                        pinned, False when left unpinned (no mask, config.json's forge_pin
                        false, the call failed: logged once, or pid is this process's own);
                        never raises
    pin_setting()       config.json's forge_pin: a real bool, else the default (true), logged
                        once ("false", 0 or None aren't false)
    pin_mode()          the environment's DECKLAB_PIN_MODE (wave 3, the combined run's battery
                        knob, harness only): PIN_MODES' "core" (the default, the above),
                        "none" (never pinned), "ccd" (slot k's core's whole L3: every logical
                        CPU sharing it, ccd_masks()) or "core-wrap" (slot k on core k mod the
                        number of cores, for more slots than cores); a bad value is "core",
                        logged once

On this PC (a 9950X3D) the cores come out as 0-15 = CPUs (0,1), (2,3) ... (30,31), the 96 MB
L3 CCD's eight first, so the first eight slots, the ones a claim takes first, run on it.
Pinning doesn't change how Java sizes itself: runner.JVM_FLAGS' -XX:ActiveProcessorCount=2
fixes that whatever the mask. Off Windows nothing is pinned (core_masks() is []).
This part comes after slots.py and imports only common and decklab.lib.config."""
import os
import sys
import threading

from decklab.lib import config

from . import common

RELATION_PROCESSOR_CORE = 0
RELATION_CACHE = 2
RELATION_ALL = 0xFFFF
CPUS_PER_CORE = 2               # SMT: each core both of its logical CPUs (anything else is "odd")
# DECKLAB_PIN_MODE (forge-trial/sim-wave3-contract.md section 8): how a slot's worker is pinned.
PIN_MODE_ENV = "DECKLAB_PIN_MODE"
PIN_MODES = ("core", "none", "ccd", "core-wrap")

_masks = None                   # core_masks()' answer, read once
_ccds = None                    # ccd_masks()' answer, read once
_masks_lock = threading.Lock()
_said = set()                   # what has been logged (each once)
_said_lock = threading.Lock()

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _k32.GetLogicalProcessorInformationEx.restype = wintypes.BOOL
    _k32.GetLogicalProcessorInformationEx.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD)]
    _k32.OpenProcess.restype = wintypes.HANDLE
    _k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _k32.SetProcessAffinityMask.restype = wintypes.BOOL
    _k32.SetProcessAffinityMask.argtypes = [wintypes.HANDLE, ctypes.c_size_t]
    _k32.CloseHandle.argtypes = [wintypes.HANDLE]
    PROCESS_SET_INFORMATION = 0x0200
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def _say_once(what, text):
    """Log text the first time what comes up in this process."""
    with _said_lock:
        if what in _said:
            return
        _said.add(what)
    common._log(text)


def pin_setting(settings=None):
    """config.json's forge_pin as a real bool: True or False only; anything else ("false",
    0, None) is the default, config.DEFAULTS', with one log line."""
    if settings is None:
        try:
            settings = common._settings()
        except Exception:           # a config.json that can't be read: the default
            settings = {}
    value = settings.get("forge_pin", config.DEFAULTS["forge_pin"])
    if isinstance(value, bool):
        return value
    _say_once(("forge_pin", repr(value)), f"config.json's forge_pin must be true or false, not {value!r}, so "
                                          f"Forge's workers are pinned as by default "
                                          f"({str(config.DEFAULTS['forge_pin']).lower()}).")
    return config.DEFAULTS["forge_pin"]


def pin_mode():
    """The environment's DECKLAB_PIN_MODE, one of PIN_MODES: "core" when it isn't set, and when
    it's none of them (logged once)."""
    value = os.environ.get(PIN_MODE_ENV) or PIN_MODES[0]
    if value in PIN_MODES:
        return value
    _say_once(("pin_mode", value), f"{PIN_MODE_ENV} must be one of {', '.join(PIN_MODES)}, not {value!r}, so "
                                   f"Forge's workers are pinned one to a core.")
    return PIN_MODES[0]


def _bits(mask):
    """The logical CPUs (bit numbers) set in mask."""
    return [i for i in range(mask.bit_length()) if mask >> i & 1]


def _group_masks(raw, at, count):
    """count GROUP_AFFINITY structures at raw[at:]: [(group, mask)] (each 16 bytes: an 8-byte
    KAFFINITY mask, a 2-byte group number, 6 reserved)."""
    out = []
    for i in range(count):
        start = at + 16 * i
        mask = int.from_bytes(raw[start:start + 8], "little")
        group = int.from_bytes(raw[start + 8:start + 10], "little")
        out.append((group, mask))
    return out


def _parse(raw):
    """GetLogicalProcessorInformationEx(RelationAll)'s buffer: (cores [[(group, mask)]], L3
    caches [(size in bytes, [(group, mask)])]). The records: Relationship (4 bytes), Size (4),
    then for a core PROCESSOR_RELATIONSHIP (Flags 1, EfficiencyClass 1, Reserved 20,
    GroupCount 2, GroupMask[]) and for a cache CACHE_RELATIONSHIP (Level 1, Associativity 1,
    LineSize 2, CacheSize 4, Type 4, Reserved 18, GroupCount 2, GroupMask[]; a GroupCount of 0
    is one group, as older Windows wrote it)."""
    cores, caches, at = [], [], 0
    while at + 8 <= len(raw):
        relation = int.from_bytes(raw[at:at + 4], "little")
        size = int.from_bytes(raw[at + 4:at + 8], "little")
        if size < 8:
            raise ValueError("a processor information record shorter than its header")
        body = at + 8
        if relation == RELATION_PROCESSOR_CORE:
            count = int.from_bytes(raw[body + 22:body + 24], "little")
            cores.append(_group_masks(raw, body + 24, count))
        elif relation == RELATION_CACHE and raw[body] == 3:
            cache_size = int.from_bytes(raw[body + 4:body + 8], "little")
            count = int.from_bytes(raw[body + 30:body + 32], "little") or 1
            caches.append((cache_size, _group_masks(raw, body + 32, count)))
        at += size
    return cores, caches


def _order(cores, caches):
    """Each core's mask, the cores ordered as the module docstring says (the largest L3
    first, then by first logical CPU; within an L3 by first logical CPU), or (None, why)
    when the topology is odd: no cores, a core or cache in more than one group or outside
    group 0, a core without exactly CPUS_PER_CORE logical CPUs, or a core in no L3."""
    if not cores:
        return None, "no cores were found"
    masks = []
    for groups in cores:
        if len(groups) != 1 or groups[0][0] != 0:
            return None, "the PC has more than one processor group"
        mask = groups[0][1]
        if len(_bits(mask)) != CPUS_PER_CORE:
            return None, f"a core has {len(_bits(mask))} logical CPUs (simultaneous multithreading is off?)"
        masks.append(mask)
    l3 = []
    for size, groups in caches:
        if any(group != 0 for group, _ in groups):
            return None, "the PC has more than one processor group"
        mask = 0
        for _, part in groups:
            mask |= part
        l3.append((size, mask))
    if not l3:
        return None, "no L3 cache was found"
    l3.sort(key=lambda cache: (-cache[0], _bits(cache[1])[0] if cache[1] else 0))
    ranked = []
    for mask in masks:
        rank = next((i for i, (_, cache) in enumerate(l3) if mask & cache == mask), None)
        if rank is None:
            return None, "a core is in no L3 cache"
        ranked.append((rank, _bits(mask)[0], mask))
    return [mask for _, _, mask in sorted(ranked)], None


def _l3_of(masks, caches):
    """For each core mask (_order's), the mask of its L3: every logical CPU in the L3 cache the
    core is in (the "ccd" pin mode), or None when a core is in none."""
    l3 = []
    for _, groups in caches:
        mask = 0
        for _, part in groups:
            mask |= part
        l3.append(mask)
    return [next((cache for cache in l3 if mask & cache == mask), None) for mask in masks]


def _read_topology():
    """The raw buffer of GetLogicalProcessorInformationEx(RelationAll); OSError when it
    can't be read."""
    size = wintypes.DWORD(0)
    _k32.GetLogicalProcessorInformationEx(RELATION_ALL, None, ctypes.byref(size))
    if not size.value:
        raise OSError(ctypes.get_last_error(), "GetLogicalProcessorInformationEx gave no size")
    buffer = ctypes.create_string_buffer(size.value)
    if not _k32.GetLogicalProcessorInformationEx(RELATION_ALL, buffer, ctypes.byref(size)):
        raise OSError(ctypes.get_last_error(), "GetLogicalProcessorInformationEx failed")
    return buffer.raw[:size.value]


def _find_masks():
    """core_masks()' answer, worked out (logged once when there's none)."""
    if sys.platform != "win32":
        return []
    try:
        masks, why = _order(*_parse(_read_topology()))
    except (OSError, ValueError, IndexError) as e:
        masks, why = None, f"the processor topology couldn't be read ({e})"
    if masks is None:
        _say_once("topology", f"Forge's workers run unpinned: {why}.")
        return []
    return masks


def core_masks():
    """Each core's affinity mask, V-Cache CCD first (the module docstring); [] without a
    topology to pin by."""
    global _masks
    with _masks_lock:
        if _masks is None:
            _masks = _find_masks()
        return list(_masks)


def _find_ccds():
    """ccd_masks()' answer, worked out ([] when there's no topology to pin by, which
    core_masks() logs)."""
    if sys.platform != "win32":
        return []
    try:
        cores, caches = _parse(_read_topology())
        masks, why = _order(cores, caches)
    except (OSError, ValueError, IndexError):
        return []
    if masks is None:
        return []
    found = _l3_of(masks, caches)
    return [] if None in found else found


def ccd_masks():
    """For each core of core_masks(), in the same order, its L3's mask (the "ccd" pin mode); []
    without a topology to pin by."""
    global _ccds
    with _masks_lock:
        if _ccds is None:
            _ccds = _find_ccds()
        return list(_ccds)


def mask_for(slot):
    """Slot slot's mask in the pin mode (pin_mode()): its core's ("core"), its core's L3's
    ("ccd"), core slot mod the number of cores' ("core-wrap"); None in mode "none", and when
    there's no such core or no topology."""
    mode = pin_mode()
    if mode == "none" or not isinstance(slot, int) or slot < 0:
        return None
    masks = core_masks()
    if mode == "core-wrap":
        return masks[slot % len(masks)] if masks else None
    if slot >= len(masks):
        return None
    if mode == "ccd":
        ccds = ccd_masks()
        return ccds[slot] if slot < len(ccds) else None
    return masks[slot]


def pin(pid, slot):
    """Pin process pid to slot slot's core (mask_for, in the pin mode): True when pinned, False
    when it's left as it is (forge_pin false, pin mode "none", no core for the slot, or Windows
    refused: logged once). Deck Lab's own
    process is never pinned (its children would inherit the mask). Never raises."""
    try:
        if int(pid) == os.getpid() or not pin_setting() or pin_mode() == "none":
            return False
        mask = mask_for(slot)
        if mask is None:
            if core_masks():
                _say_once(("slot", slot), f"Slot {slot} has no core of its own to pin to, so its Forge workers "
                                          f"run unpinned.")
            return False
        if sys.platform != "win32":
            return False
        handle = _k32.OpenProcess(PROCESS_SET_INFORMATION | PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not handle:
            _say_once("open", f"A Forge process couldn't be pinned to a core (error {ctypes.get_last_error()}), "
                              f"so it runs unpinned.")
            return False
        try:
            if not _k32.SetProcessAffinityMask(handle, mask):
                _say_once("set", f"A Forge process couldn't be pinned to a core (error {ctypes.get_last_error()}), "
                                 f"so it runs unpinned.")
                return False
        finally:
            _k32.CloseHandle(handle)
        return True
    except Exception as e:          # never raises: the worker plays unpinned
        _say_once("error", f"Forge's workers couldn't be pinned ({e!r}), so they run unpinned.")
        return False
