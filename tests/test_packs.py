"""Genre packs: every pack loads, passes the schema, and (when a v1 checkout is given) equals the v1 genre it came from.

    python -m pytest tests                          (packs + song document)
    SL1_PATH=../studio-lab python -m pytest tests   (also checks the packs against Studio Lab 1)
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sl2 import packs  # noqa: E402

IDS = sorted(packs.index())


def test_there_are_packs():
    assert len(IDS) > 300


@pytest.mark.parametrize('gid', IDS)
def test_pack_valid(gid):
    packs.validate(packs.load(gid), gid)


@pytest.mark.skipif(not os.environ.get('SL1_PATH'), reason='set SL1_PATH to a Studio Lab 1 checkout')
def test_packs_equal_v1():
    sys.path.insert(0, os.path.abspath(os.environ['SL1_PATH']))
    from sgcore.styles import STYLES
    from tools.convert_v1_styles import _plain
    assert set(STYLES) == set(IDS)
    for gid, v1 in STYLES.items():
        assert packs.load(gid) == _plain(v1), gid
