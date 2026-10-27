"""Offline test for tools/link-stress.py: the sequence / fps parser on `v4l2-ctl --verbose` output captured on esteban
(7.2.12-gcov, 2026-10-27, --stream-count=10 --stream-skip=5, cut to 7 buffers)."""
import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location("link_stress", Path(__file__).resolve().parents[1] / "tools" / "link-stress.py")
ls = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ls)

SAMPLE = """\t\tVIDIOC_STREAMON returned 0 (Success)
cap dqbuf: 0 seq:      1 bytesused: 399360 ts: 112853.906269 field: None (ts-monotonic, ts-src-eof)
cap dqbuf: 1 seq:      2 bytesused: 399360 ts: 112853.939775 delta: 33.506 ms field: None (ts-monotonic, ts-src-eof)
cap dqbuf: 2 seq:      3 bytesused: 399360 ts: 112853.972984 delta: 33.209 ms field: None (ts-monotonic, ts-src-eof)
cap dqbuf: 3 seq:      4 bytesused: 399360 ts: 112854.006261 delta: 33.277 ms field: None (ts-monotonic, ts-src-eof)
cap dqbuf: 0 seq:      5 bytesused: 399360 ts: 112854.039585 delta: 33.324 ms fps: 30.00 field: None (ts-monotonic, ts-src-eof)
cap dqbuf: 1 seq:      6 bytesused: 399360 ts: 112854.073020 delta: 33.435 ms fps: 29.98 field: None (ts-monotonic, ts-src-eof)
cap dqbuf: 2 seq:      7 bytesused: 399360 ts: 112854.106235 delta: 33.215 ms fps: 30.01 field: None (ts-monotonic, ts-src-eof)

VIDIOC_QUERYCAP: ok
"""


def test_parse_complete_stream():
    assert ls.parse_stream(SAMPLE) == (7, 0, 30.01)


def test_parse_gap_and_empty():
    gapped = "\n".join(l for l in SAMPLE.splitlines() if "seq:      3 " not in l and "seq:      4 " not in l)
    assert ls.parse_stream(gapped) == (5, 2, 30.01)
    assert ls.parse_stream("\t\tVIDIOC_REQBUFS returned 0 (Success)\n") == (0, 0, None)
