"""Tests for the PC's physical cores (decklab/lib/forge/cores.py, simulation wave 2's R01b):
reading GetLogicalProcessorInformationEx's records, ordering the cores V-Cache CCD first (the
largest L3 first), the topologies that leave workers unpinned (SMT off, more than one
processor group, a core in no L3), config.json's forge_pin, and pinning a process to its
slot's core (a real child process on Windows), never Deck Lab's own.

Run from the repo root: python scripts/test_fixtures.py decklab.tests.test_forge_cores
"""
import os
import subprocess
import sys
import unittest
from unittest import mock

from decklab.lib.forge import common, cores


def core(mask, group=0):
    """A RelationProcessorCore record (PROCESSOR_RELATIONSHIP, one GROUP_AFFINITY)."""
    body = bytes([1, 0]) + bytes(20) + (1).to_bytes(2, "little") + mask.to_bytes(8, "little") \
        + group.to_bytes(2, "little") + bytes(6)
    return (0).to_bytes(4, "little") + (8 + len(body)).to_bytes(4, "little") + body


def cache(level, size, mask, group=0, count=1):
    """A RelationCache record (CACHE_RELATIONSHIP, one GROUP_AFFINITY; count 0 as older Windows wrote it)."""
    body = bytes([level, 16]) + (64).to_bytes(2, "little") + size.to_bytes(4, "little") + (0).to_bytes(4, "little") \
        + bytes(18) + count.to_bytes(2, "little") + mask.to_bytes(8, "little") + group.to_bytes(2, "little") + bytes(6)
    return (2).to_bytes(4, "little") + (8 + len(body)).to_bytes(4, "little") + body


def other(relation=1):
    """A record of another kind (a NUMA node, a package...), which is passed over."""
    body = bytes(24)
    return relation.to_bytes(4, "little") + (8 + len(body)).to_bytes(4, "little") + body


MB = 1 << 20


def two_ccds(vcache_first=True, cores_per_ccd=4):
    """A 2-CCD part with SMT: CCD0 = CPUs 0..2n-1, CCD1 the rest; the V-Cache L3 (96 MB) on CCD0,
    or on CCD1."""
    records = []
    for i in range(2 * cores_per_ccd):
        records.append(core(0b11 << (2 * i)))
        records.append(cache(2, 1 * MB, 0b11 << (2 * i)))
    half = (1 << (2 * cores_per_ccd)) - 1
    big, small = (96 * MB, 32 * MB) if vcache_first else (32 * MB, 96 * MB)
    records.append(cache(3, big, half))
    records.append(cache(3, small, half << (2 * cores_per_ccd)))
    records.append(other())
    return b"".join(records)


class TopologyTests(unittest.TestCase):

    def setUp(self):
        cores._said.clear()
        self.addCleanup(cores._said.clear)

    def order(self, raw):
        return cores._order(*cores._parse(raw))

    def test_the_v_cache_ccd_comes_first(self):
        masks, why = self.order(two_ccds(vcache_first=True))
        self.assertIsNone(why)
        self.assertEqual(masks, [0b11 << (2 * i) for i in range(8)])
        # The V-Cache (the larger L3) on the second CCD: its cores first, each CCD's in CPU order.
        masks, why = self.order(two_ccds(vcache_first=False))
        self.assertEqual(masks, [0b11 << (2 * i) for i in (4, 5, 6, 7, 0, 1, 2, 3)])

    def test_equal_l3s_go_by_their_first_cpu(self):
        raw = b"".join([core(0b1100), core(0b11), cache(3, 32 * MB, 0b1100), cache(3, 32 * MB, 0b11)])
        self.assertEqual(self.order(raw), ([0b11, 0b1100], None))

    def test_a_cache_record_with_no_group_count_is_one_group(self):
        raw = b"".join([core(0b11), core(0b1100), cache(3, 32 * MB, 0b1111, count=0)])
        self.assertEqual(self.order(raw), ([0b11, 0b1100], None))

    def test_odd_topologies_leave_workers_unpinned(self):
        cases = {
            "no cores were found": cache(3, 32 * MB, 0b11),
            "a core has 1 logical CPUs (simultaneous multithreading is off?)":
                b"".join([core(0b1), core(0b10), cache(3, 32 * MB, 0b11)]),
            "the PC has more than one processor group": b"".join([core(0b11, group=1), cache(3, 32 * MB, 0b11)]),
            "no L3 cache was found": b"".join([core(0b11), cache(2, MB, 0b11)]),
            "a core is in no L3 cache": b"".join([core(0b11), core(0b1100), cache(3, 32 * MB, 0b11)]),
        }
        for why, raw in cases.items():
            with self.subTest(why=why):
                self.assertEqual(self.order(raw), (None, why))

    def test_a_record_shorter_than_its_header_is_an_error(self):
        with self.assertRaises(ValueError):
            cores._parse((0).to_bytes(4, "little") + (4).to_bytes(4, "little"))

    def test_the_masks_are_read_once_and_logged_once_when_odd(self):
        logged = []
        with mock.patch.object(cores, "_masks", None), mock.patch.object(common, "_log", logged.append), \
                mock.patch.object(cores, "sys", mock.Mock(platform="win32")), \
                mock.patch.object(cores, "_read_topology", return_value=two_ccds()) as read:
            self.assertEqual(len(cores.core_masks()), 8)
            self.assertEqual(cores.mask_for(1), 0b1100)
            self.assertIsNone(cores.mask_for(8))
            self.assertIsNone(cores.mask_for(-1))
            self.assertEqual(read.call_count, 1)            # read once, kept
        with mock.patch.object(cores, "_masks", None), mock.patch.object(common, "_log", logged.append), \
                mock.patch.object(cores, "sys", mock.Mock(platform="win32")), \
                mock.patch.object(cores, "_read_topology", side_effect=OSError(5, "Access is denied")):
            self.assertEqual(cores.core_masks(), [])
            self.assertIsNone(cores.mask_for(0))
        self.assertEqual(len(logged), 1)
        self.assertIn("Forge's workers run unpinned: the processor topology couldn't be read", logged[0])

    @unittest.skipUnless(sys.platform == "win32", "the topology is read on Windows")
    def test_this_pcs_cores(self):
        masks = cores.core_masks()
        if not masks:
            self.skipTest("this PC's topology is one Deck Lab doesn't pin by")
        self.assertTrue(all(bin(mask).count("1") == 2 for mask in masks))
        union = 0
        for mask in masks:
            self.assertEqual(union & mask, 0)           # no CPU in two cores
            union |= mask
        self.assertEqual(union.bit_count(), 2 * len(masks))


class PinSettingTests(unittest.TestCase):

    def setUp(self):
        cores._said.clear()
        self.addCleanup(cores._said.clear)

    def test_forge_pin_must_be_a_real_bool(self):
        logged = []
        with mock.patch.object(common, "_log", logged.append):
            self.assertIs(cores.pin_setting({"forge_pin": False}), False)
            self.assertIs(cores.pin_setting({"forge_pin": True}), True)
            self.assertIs(cores.pin_setting({}), True)                 # config.DEFAULTS'
            for value in ("false", 0, None, "no"):
                self.assertIs(cores.pin_setting({"forge_pin": value}), True, value)
            self.assertIs(cores.pin_setting({"forge_pin": "false"}), True)     # said once
        self.assertEqual(len(logged), 4)
        self.assertEqual(logged[0], "config.json's forge_pin must be true or false, not 'false', so Forge's "
                                    "workers are pinned as by default (true).")
        with mock.patch.object(common, "_settings", return_value={"forge_pin": False}):
            self.assertIs(cores.pin_setting(), False)


@unittest.skipUnless(sys.platform == "win32", "pinning is Windows-only")
class PinTests(unittest.TestCase):

    def setUp(self):
        cores._said.clear()
        self.addCleanup(cores._said.clear)
        self.child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        self.addCleanup(self.child.wait, 10)
        self.addCleanup(self.child.kill)

    def affinity(self, pid):
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenProcess.restype = wintypes.HANDLE
        handle = k32.OpenProcess(0x1000, False, pid)            # PROCESS_QUERY_LIMITED_INFORMATION
        process, system = ctypes.c_size_t(), ctypes.c_size_t()
        try:
            self.assertTrue(k32.GetProcessAffinityMask(wintypes.HANDLE(handle), ctypes.byref(process),
                                                       ctypes.byref(system)))
        finally:
            k32.CloseHandle(wintypes.HANDLE(handle))
        return process.value

    def test_a_process_is_pinned_to_its_slots_core(self):
        with mock.patch.object(cores, "core_masks", return_value=[0b11, 0b1100]), \
                mock.patch.object(common, "_settings", return_value={"forge_pin": True}):
            self.assertTrue(cores.pin(self.child.pid, 1))
            self.assertEqual(self.affinity(self.child.pid), 0b1100)
            self.assertTrue(cores.pin(self.child.pid, 0))           # a worker's next slot: its core
            self.assertEqual(self.affinity(self.child.pid), 0b11)

    def test_what_leaves_a_process_unpinned(self):
        before = self.affinity(self.child.pid)
        logged = []
        with mock.patch.object(cores, "core_masks", return_value=[0b11, 0b1100]), \
                mock.patch.object(common, "_log", logged.append):
            with mock.patch.object(common, "_settings", return_value={"forge_pin": False}):
                self.assertFalse(cores.pin(self.child.pid, 0))     # forge_pin false
            with mock.patch.object(common, "_settings", return_value={}):
                self.assertFalse(cores.pin(os.getpid(), 0))         # Deck Lab's own process: never
                self.assertFalse(cores.pin(self.child.pid, 2))      # a slot with no core of its own
                self.assertFalse(cores.pin(self.child.pid, 2))      # (said once)
                self.assertFalse(cores.pin(2 ** 31 - 1, 0))         # no such process
                with mock.patch.object(cores._k32, "SetProcessAffinityMask", return_value=False):
                    self.assertFalse(cores.pin(self.child.pid, 0))
                with mock.patch.object(cores, "mask_for", side_effect=RuntimeError("a bug")):
                    self.assertFalse(cores.pin(self.child.pid, 0))  # never raises
        self.assertEqual(self.affinity(self.child.pid), before)
        self.assertEqual(len(logged), 4, logged)
        self.assertIn("Slot 2 has no core of its own", logged[0])
        with mock.patch.object(cores, "core_masks", return_value=[]), \
                mock.patch.object(common, "_settings", return_value={}):
            self.assertFalse(cores.pin(self.child.pid, 0))          # no topology: already said by core_masks


if __name__ == "__main__":
    unittest.main()
