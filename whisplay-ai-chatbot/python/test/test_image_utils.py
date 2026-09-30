"""Camera conversion must not load OpenCV while the chatbot display starts."""

import builtins
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

PYTHON_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PYTHON_ROOT))

import utils  # noqa: E402


@pytest.fixture(autouse=True)
def clear_camera_import_cache():
    utils._camera_cv.cache_clear()
    yield
    utils._camera_cv.cache_clear()


@pytest.fixture
def frame():
    return np.array([[[255, 0, 0], [0, 255, 0]],
                     [[0, 0, 255], [255, 255, 255]]], dtype=np.uint8)


# Nearest-neighbour expansion from 2x2 to 4x2, in display byte order.
EXPECTED = bytes.fromhex("f800 f800 07e0 07e0 001f 001f ffff ffff")


def test_display_utilities_do_not_import_opencv_in_a_fresh_process():
    script = """
import importlib.abc
import sys

class RejectOpenCV(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'cv2' or fullname.startswith('cv2.'):
            raise AssertionError('OpenCV imported during display startup')

sys.meta_path.insert(0, RejectOpenCV())
import utils
assert 'cv2' not in sys.modules
assert utils.ColorUtils.rgb565_to_rgb255(0xf800) == (255, 0, 0)
"""
    result = subprocess.run([sys.executable, "-c", script], cwd=PYTHON_ROOT,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr


def test_camera_uses_opencv_and_caches_the_import(frame, monkeypatch):
    resized = np.repeat(frame, 2, axis=1)
    cv = SimpleNamespace(INTER_NEAREST=object(), resize=Mock(return_value=resized))
    real_import = builtins.__import__
    imports = []

    def import_camera(name, *args, **kwargs):
        if name == "cv2":
            imports.append(name)
            return cv
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", import_camera)
    for _ in range(2):
        assert utils.ImageUtils.convertCameraFrameToRGB565(frame, 4, 2) == EXPECTED
    assert imports == ["cv2"]
    assert cv.resize.call_count == 2
    for call in cv.resize.call_args_list:
        assert call.args[0] is frame
        assert call.args[1] == (4, 2)
        assert call.kwargs == {"interpolation": cv.INTER_NEAREST}


def test_camera_falls_back_to_pillow_and_caches_missing_opencv(frame, monkeypatch):
    real_import = builtins.__import__
    imports = []

    def no_camera(name, *args, **kwargs):
        if name == "cv2":
            imports.append(name)
            raise ImportError("OpenCV is not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_camera)
    for _ in range(2):
        assert utils.ImageUtils.convertCameraFrameToRGB565(frame, 4, 2) == EXPECTED
    assert imports == ["cv2"]
