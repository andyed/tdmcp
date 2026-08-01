"""Unit tests for the timeline transport bridge module.

Mirrors ``test_connect_service.py``: install a stub ``td`` module whose
``op('/').time`` is a tiny fake, drive ``transport_service.control()`` off-TD,
and assert (a) the side-effect on the fake state and (b) the returned state dict.

Run from the repo root: ``python3 -m unittest discover -s td/tests``.
"""

import os
import sys
import types
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_MODULES = os.path.abspath(os.path.join(_HERE, "..", "modules"))
if _MODULES not in sys.path:
    sys.path.insert(0, _MODULES)

# transport_service does ``import td`` INSIDE control(); reach the shared stub
# under sys.modules["td"] (sibling tests setdefault() it) and patch on it.
_td_stub = types.ModuleType("td")
sys.modules.setdefault("td", _td_stub)
_TD = sys.modules["td"]

from mcp.services import transport_service as ts  # noqa: E402


class _FakeTime:
    def __init__(self):
        self.play = False
        self.frame = 0
        self.rate = 60.0
        self.start = 0
        self.end = 600


class _FakeRoot:
    def __init__(self):
        self.time = _FakeTime()


class _TdPatch:
    """Swap ``td.op`` for a test's lifetime."""

    def __init__(self):
        self.root = _FakeRoot()

    def __enter__(self):
        self._saved = getattr(_TD, "op", None)
        _TD.op = lambda path: self.root if path == "/" else None
        return self

    def __exit__(self, *a):
        _TD.op = self._saved


class TransportTests(unittest.TestCase):
    def test_play_sets_root_time_play_and_returns_state(self):
        with _TdPatch() as p:
            state = ts.control("play")
        self.assertTrue(p.root.time.play)
        self.assertEqual(state["action"], "play")
        self.assertTrue(state["play"])
        self.assertEqual(state["startFrame"], 0)
        self.assertEqual(state["endFrame"], 600)
        self.assertEqual(state["fps"], 60.0)

    def test_pause_clears_root_time_play(self):
        with _TdPatch() as p:
            p.root.time.play = True
            state = ts.control("pause")
        self.assertFalse(p.root.time.play)
        self.assertFalse(state["play"])

    def test_seek_clamps_to_endFrame_and_updates_root_time_frame(self):
        with _TdPatch() as p:
            state = ts.control("seek", frame=9999)
        self.assertEqual(p.root.time.frame, 600)  # clamped
        self.assertEqual(state["frame"], 600)

    def test_seek_clamps_to_startFrame(self):
        with _TdPatch() as p:
            state = ts.control("seek", frame=-50)
        self.assertEqual(p.root.time.frame, 0)
        self.assertEqual(state["frame"], 0)

    def test_seek_without_frame_raises(self):
        with _TdPatch():
            with self.assertRaises(ValueError) as cm:
                ts.control("seek")
            self.assertIn("frame", str(cm.exception))

    def test_cue_explains_root_timeline_has_no_named_cue_api(self):
        with _TdPatch():
            with self.assertRaises(ValueError) as cm:
                ts.control("cue", cue_name="verse")
            self.assertIn("manage_cue", str(cm.exception))
            self.assertIn("verse", str(cm.exception))

    def test_cue_without_name_raises(self):
        with _TdPatch():
            with self.assertRaises(ValueError):
                ts.control("cue")

    def test_rate_sets_root_time_fps(self):
        with _TdPatch() as p:
            state = ts.control("rate", rate=30)
        self.assertEqual(p.root.time.rate, 30)
        self.assertEqual(state["rate"], 30)
        self.assertEqual(state["fps"], 30)

    def test_rate_without_rate_raises(self):
        with _TdPatch():
            with self.assertRaises(ValueError):
                ts.control("rate")

    def test_unknown_action_raises(self):
        with _TdPatch():
            with self.assertRaises(ValueError):
                ts.control("teleport")


if __name__ == "__main__":
    unittest.main()
