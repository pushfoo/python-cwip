from io import BytesIO, StringIO
import subprocess
from unittest.mock import MagicMock, Mock

from cwip import MajorMinorPatchVersion, WLPasteRunner


# Taken from Debian 13's output
_VERSION = b"""wl-clipboard 2.2.1
Copyright (C) 2018-2023 Sergey Bugaev
License GPLv3+: GNU GPL version 3 or later <https://gnu.org/licenses/gpl.html>.
This is free software: you are free to change and redistribute it.
There is NO WARRANTY, to the extent permitted by law.
"""


def test_creation(monkeypatch):
    with monkeypatch.context() as patched:
        method = MagicMock()
        process = MagicMock(subprocess.CompletedProcess)
        process.stdout = _VERSION
        process.returncode = 0
        method.return_value = process

        patched.setattr(subprocess, 'run', method)
        runner = WLPasteRunner()
        assert runner.version == MajorMinorPatchVersion(2, 2, 1)


# Close enough to an Electron application for now
_LIST_TYPES_TEXT_AND_HTML = b"""text/plain
text/plain;encoding=utf8
chrome/x-source-url
"""


def test_list_types(monkeypatch):
    with monkeypatch.context() as patched:
        process = MagicMock(subprocess.CompletedProcess)
        process.stdout = _VERSION
        process.returncode = 0
        method = Mock(return_value=process)

        patched.setattr(subprocess, 'run', method)

        runner = WLPasteRunner()

        second_return = Mock(subprocess.CompletedProcess)
        second_return.stdout = _LIST_TYPES_TEXT_AND_HTML
        second_return.returncode = 0
        method.return_value = second_return

        types = tuple(runner.list_types())

        assert types == (
            "text/plain",
            "text/plain;encoding=utf8",
            "chrome/x-source-url"
        )


def test_open_mime_as_bytesio(monkeypatch):
    with monkeypatch.context() as patched:
        process = MagicMock(subprocess.CompletedProcess)
        process.stdout = _VERSION
        process.returncode = 0
        method = Mock(return_value=process)
        patched.setattr(subprocess, 'run', method)

        runner = WLPasteRunner()
        method.reset_mock()
        new_return = MagicMock(subprocess.CompletedProcess)
        new_return.stdout = b"\x01\x02\x03"
        new_return.returncode = 0
        method.return_value = new_return

        with runner.open_mime_as_bytesio('some/bytes') as stream:
            assert isinstance(stream, BytesIO)
            assert stream.getvalue() == b"\x01\x02\x03"


def test_open_mime_as_stringio(monkeypatch):
    with monkeypatch.context() as patched:
        process = MagicMock(subprocess.CompletedProcess)
        process.stdout = _VERSION
        process.returncode = 0
        method = Mock(return_value=process)
        patched.setattr(subprocess, 'run', method)

        runner = WLPasteRunner()
        method.reset_mock()
        new_return = MagicMock(subprocess.CompletedProcess)
        new_return.stdout = b"abcdefg"
        new_return.returncode = 0
        method.return_value = new_return

        with runner.open_mime_as_stringio('text/plain') as stream:
            assert isinstance(stream, StringIO)
            assert stream.getvalue() == "abcdefg"
