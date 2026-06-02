from io import BytesIO, StringIO
import subprocess
from unittest.mock import MagicMock, Mock

from cwip import MajorMinorPatchVersion, XClipPasteRunner


# Taken from Debian 13's output
_VERSION = b"""xclip version 0.13
Copyright (C) 2001-2008 Kim Saunders et al.
Distributed under the terms of the GNU GPL
"""


def test_creation(monkeypatch):
    with monkeypatch.context() as patched:
        method = MagicMock()
        process = MagicMock(subprocess.CompletedProcess)
        process.stderr = _VERSION
        process.stdout = b""  # list_types() expects there to be stdout bytes
        process.returncode = 0
        method.return_value = process

        patched.setattr(subprocess, 'run', method)
        runner = XClipPasteRunner()
        assert runner.version == MajorMinorPatchVersion(0, 13)


# Close enough to an Electron application for now
_LIST_TYPES_TEXT_AND_HTML = b"""TIMESTAMP
TARGETS
SAVE_TARGETS
MULTIPLE
STRING
UTF8_STRING
TEXT
chromium/x-internal-source-rfh-token
chromium/x-source-url
chromium/x-web-custom-data
text/html
text/plain
text/plain;charset=utf-8
"""
_FILTERED_TUPLE = tuple(
    filter(
        lambda s: s.islower(),
        _LIST_TYPES_TEXT_AND_HTML.decode().splitlines()
    ))


def test_list_types(monkeypatch):
    with monkeypatch.context() as patched:
        process = MagicMock(subprocess.CompletedProcess)
        process.stderr = _VERSION
        process.stdout = b""
        process.returncode = 0
        method = Mock(return_value=process)

        patched.setattr(subprocess, 'run', method)

        runner = XClipPasteRunner()

        second_return = Mock(subprocess.CompletedProcess)
        second_return.stdout = _LIST_TYPES_TEXT_AND_HTML
        second_return.returncode = 0
        method.return_value = second_return

        types = tuple(runner.list_types())

        assert types == _FILTERED_TUPLE


def test_open_mime_as_bytesio(monkeypatch):
    with monkeypatch.context() as patched:
        process = MagicMock(subprocess.CompletedProcess)
        process.stderr = _VERSION
        process.stdout = b""
        process.returncode = 0
        method = Mock(return_value=process)
        patched.setattr(subprocess, 'run', method)

        runner = XClipPasteRunner()
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
        process.stderr = _VERSION
        process.stdout = b""
        process.returncode = 0
        method = Mock(return_value=process)
        patched.setattr(subprocess, 'run', method)

        runner = XClipPasteRunner()
        method.reset_mock()
        new_return = MagicMock(subprocess.CompletedProcess)
        new_return.stdout = b"abcdefg"
        new_return.returncode = 0
        method.return_value = new_return

        with runner.open_mime_as_stringio('text/plain') as stream:
            assert isinstance(stream, StringIO)
            assert stream.getvalue() == "abcdefg"
