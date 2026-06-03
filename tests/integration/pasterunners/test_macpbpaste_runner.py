from io import StringIO
from pathlib import Path
import subprocess
from unittest.mock import MagicMock, Mock

import pytest

from cwip import MacPbpastePasterunner

_VERSION = b"""ProductName: macOS
ProductVersion: 15.6.1
BuildVersion: 24G90
"""

@pytest.fixture(
    # Although technically a shell built-in under macOS,
    # this seems to make type annotations work cleaner so
    # we may as well test it to ensure API consitency.
    params=["sw_version", Path("sw_version")],
    autouse=True
)
def executable(request):
    return request.param

def test_creation(monkeypatch, executable):
    with monkeypatch.context() as patched:
        method = MagicMock()
        process = MagicMock(subprocess.CompletedProcess)
        process.stdout = _VERSION
        process.returncode = 0
        method.return_value = process

        patched.setattr(subprocess, 'run', method)
        runner = MacPbpastePasterunner(executable)
        assert runner.version == _VERSION.decode()
        assert runner.executable == str(executable)


def test_list_types(executable):
    runner = MacPbpastePasterunner(executable)
    types = tuple(runner.list_types())
    assert types == (
        "text/plain",
    )


def test_open_mime_as_stringio(monkeypatch, executable):
    with monkeypatch.context() as patched:
        process = MagicMock(subprocess.CompletedProcess)
        process.stdout = _VERSION
        process.returncode = 0
        method = Mock(return_value=process)
        patched.setattr(subprocess, 'run', method)

        runner = MacPbpastePasterunner(executable)
        method.reset_mock()
        new_return = MagicMock(subprocess.CompletedProcess)
        new_return.stdout = b"abcdefg"
        new_return.returncode = 0
        method.return_value = new_return

        with runner.open_mime_as_stringio('text/plain') as stream:
            assert isinstance(stream, StringIO)
            assert stream.getvalue() == "abcdefg"