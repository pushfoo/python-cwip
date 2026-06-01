from contextlib import contextmanager
from pathlib import Path
from unittest.mock import sentinel

import pytest

from cwip import open_stdio


BASIC_MODES = ("r", "w", "rb", "wb")
ADVANCED_MODES = (
    "a", "at", 'ab', 'a+', 'a+t',
    'x', 'xt', 'xr', 'x+', 't+t'
    "rw", "r+w", "r+b", 'rw+t',
    "w+b", 'w+t'
)
ALL_MODES = (*BASIC_MODES, *ADVANCED_MODES)


@pytest.fixture(params=BASIC_MODES)
def basic_open_mode(request):
    return request.param


@pytest.fixture(params=ADVANCED_MODES)
def advanced_open_mode(request):
    return request.param


@pytest.fixture(params=ALL_MODES)
def any_open_mode(request):
    return request.param


def test_open_stdio_rejects_advanced_modes_when_path_is_dash(
    advanced_open_mode
):
    with pytest.raises(ValueError):
        with open_stdio("-", mode=advanced_open_mode) as _:
            ...

def test_open_stdio_accepts_basic_modes_when_path_is_dash(
    basic_open_mode,
    monkeypatch,
):
    with monkeypatch.context() as ctx:
        mode_sentinel = getattr(sentinel, f"dash_path-{basic_open_mode}")
        def fake_get_stdio_stream(mode):
            if mode == basic_open_mode:
                return mode_sentinel
        ctx.setattr('cwip._get_stdio_stream', fake_get_stdio_stream)
        with open_stdio("-", mode=basic_open_mode) as stream:
            assert stream is mode_sentinel


@pytest.fixture(params=[Path.home(), Path.cwd(), Path("/tmp"), Path("file.txt")])
def raw_non_dash_path(request) -> Path:
    return request.param

@pytest.fixture(params=[str, Path])
def path_type(request) -> type:
    return request.param


@pytest.fixture
def non_dash_path(raw_non_dash_path, path_type) -> str | Path:
    return path_type(raw_non_dash_path)


def test_open_stdio_accepts_all_modes_when_path_is_not_dash(
    any_open_mode,
    monkeypatch,
    non_dash_path
):
    with monkeypatch.context() as ctx:
        mode_sentinel = getattr(sentinel, f"nondash_path-{any_open_mode}")

        @contextmanager
        def fake_open(path: str | Path, mode: str  = "r"):
            yield mode_sentinel

        ctx.setattr('cwip._open', fake_open)
        with open_stdio(non_dash_path, mode=any_open_mode) as stream:
            assert stream is mode_sentinel
