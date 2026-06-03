import abc
import argparse
from dataclasses import asdict, dataclass
import logging
import os
import re
import subprocess
import sys


from contextlib import ExitStack, contextmanager
from enum import StrEnum, auto
from io import BytesIO, StringIO
from pathlib import Path
from typing import ClassVar, Final, Generator, Iterable, Protocol, Self, TypeVar


__all__ = [
    'DEV_NULL',
    'UTF8',
    'VERSION_PATTERN',
    'parse_version',
    'RunnerException',
    'NoVersionFound',
    'CommandNotFound',
    'open_stdio',
    'BaseRunner',
    'PasteRunnerABC',
    'EmptyClipboardException',
    'WLPasteRunner',
    'XClipPasteRunner',
    'ClipboardActionEnum',
    'paste_data_type_to_path_or_stdout',
    'paste_from_clipboard'
]


VERSION_PATTERN = re.compile(r"""
(?P<major>[0-9]+)
(?:
   \.(?P<minor>[0-9]+)
   (?:
      \.(?P<patch>[0-9]+)
   )?
)?
(?P<extra>[^0-9][a-zA-Z0-9]*)?
""", re.X)


MAC_VERSION_PATTERN = re.compile(r"""
    ProductName:\ macOS\n
    ProductVersion:\ (?P<major>[0-9]+)\.(?P<minor>[0-9]+)\.(?P<patch>[0-9]+)\n
    BuildVersion:\ (?P<extra>[a-zA-Z0-9]+)\n?""", re.X)


def _parse_version(raw: str, pattern: re.Pattern) -> str:
    """Parse a `raw` A.B.Cd pattern as a Version instance.

    It raises a ValueError if it fails to match VERSION_PATTERN.

    Arguments:
        raw: a raw string.

    Returns:
        A Version instance.
    """

    if not isinstance(raw, str):
        raise TypeError(f"raw must be a str, not {raw=!r}")
    elif raw == "":
        raise ValueError(f"raw must be a non-empty string, not ''")

    match = pattern.match(raw)
    if not match:
        raise ValueError(f"{raw=!r} does not match {pattern=!r}")

    return match.group(0)


def parse_version(raw: str) -> str:
    return _parse_version(raw, VERSION_PATTERN)


def parse_mac_version(raw: str) -> str:
    return _parse_version(raw, MAC_VERSION_PATTERN)


_T_In_contra = TypeVar('_T_In_contra', contravariant=True)
_T_Out_co = TypeVar('_T_Out_co', covariant=True)


class _Converter(Protocol[_T_In_contra, _T_Out_co]):

    def __call__(self, __input: _T_In_contra) -> _T_Out_co:
        ...


_VERSION_LONG_FLAG: Final[str] = '--version'
_VERSION_ARGS: Final[tuple[str]] = (_VERSION_LONG_FLAG,)
DEV_NULL: Final[str] = '/dev/null'
UTF8: Final[str] = 'utf8'


class RunnerException(RuntimeError):
    """Base runner exception."""
    ...

    @classmethod
    def from_called_process_error(
        cls,
        e: subprocess.CalledProcessError,
        encoding: str = UTF8
    ) -> Self:
        first_line_raw: bytes = e.stderr.split(b'\n', 1)[0]
        first_line = first_line_raw.decode(encoding=encoding)
        instance = cls(first_line)
        instance.__cause__ = e
        return instance


class CommandNotFound(RunnerException):
    """Executable or shell command was not found. to run at all."""
    ...


class NoVersionFound(RunnerException):
    """The executable ran, but no version was found."""
    ...


class ClipboardException(Exception):
    """A clipboard data problem."""
    ...


class EmptyClipboardException(ClipboardException):
    """There is no data in the clipboard."""
    ...


class NoMatchingClipboardData(ClipboardException, KeyError):
    """No matching type was found in the clipboard."""
    ...


def parse_version_prefixed[V](
    discard_all_but_first_line: str,
    parser: _Converter[str, str] = parse_version
) -> str:
    """Try parsing each space-separated chunk of the first line into a Version.

    Arguments:
        discard_all_but_first_line: A string hich may hold a version string.
        parser: A callable which extracts a version type from a string.
    """
    first_line = discard_all_but_first_line.split("\n")[0]
    chunks = first_line.split()
    for chunk in chunks:
        try:
            version = parser(chunk)
            return version
        except Exception as e:
            pass
    raise NoVersionFound(
        f"No version found for {first_line=!r} with {parser=!r}")


class StdioStream(StrEnum):
    STDOUT = auto()
    STDIN = auto()
    STDERR = auto()


class BaseRunner:
    """A runner for a task or command set.

    Since version notation varies between projects, this
    type is a generic. The passed `version_parser`'s return
    type act as the single source of truth for both:
    1. the version data type
    2. how to parse it from strings

    Arguments:
        base_executable: A command name or path to an executable.
        version_parser: Reads a version object from a string.
        test_executable: Test the runner immediately on init.
    """

    version_on: ClassVar[StdioStream] = StdioStream.STDOUT

    @property
    def executable(self) -> str:
        return self._executable

    @property
    def version(self) -> str | None:
        return self._version

    def __init__(
        self,
        executable: str | Path,
        version_parser: _Converter[str, str] | None = parse_version,
        test_executables: bool = True
    ):
        super().__init__()

        if not isinstance(executable, (str, Path)):
            raise TypeError(f"{executable=!r} is not a string")
        self._executable: str = str(executable)

        if version_parser is not None and not callable(version_parser):
            raise TypeError(f"{version_parser=!r} is not callable")

        self._version = None
        self._version_parser = version_parser
        if test_executables:
            self.test_executables()

    def _get_flags_for_version_check(self) -> tuple[str, ...]:
        return _VERSION_ARGS

    def _detect_version(self) -> bool:
        args = self._get_flags_for_version_check()
        success: bool = False
        utf8 = None
        try:
            utf8 = self._run_cmd_read_str(*args, which=str(self.version_on))
            version = self._parse_version(utf8)
            success = True
        except Exception as e:
            if utf8 is not None:
                line = utf8 if len(utf8) < 20 else repr(f"{utf8[:20]}...")
                msg = f"Failed to find a version from output {line!r}"
            else:
                msg = f"Failed to run {self._executable} with {args=!r}"
            raise NoVersionFound(msg) from e
        self._version = version

        return success

    def test_executables(self) -> bool:
        """Verify the runner appears to work.

        The default implementation runs the base_executable
        with `--version` as the argument, then returns `True`
        if:
        1. The return code was zero, signalling no errors
        2. A version was parsed successfully from the output

        Returns:
            True if executable worked.
        """
        return self._detect_version()

    def _parse_version(self, raw: str) -> str:
        if not self._version_parser:
            raise NotImplementedError(
                f"Override this method or pass a custom version parser function")
        return self._version_parser(raw)

    def _run_cmd_raw(
        self,
        *args: str,
        shell: bool = True,
        check: bool = False
    ) -> subprocess.CompletedProcess:
        """Internal subprocess helper.

        Arguments:
            args: Arguments to the base executable.
            shell: Same as subprocess.run
            check: Same as subprocess.run
        Returns:
            A completed subprocess.
        """
        parts = [self._executable, *args]
        joined = ' '.join(parts)
        cmd = subprocess.run(
            joined, shell=shell, capture_output=True, check=check)
        return cmd

    def _run_cmd_read_bytes(
        self,
        *args: str,
        shell: bool = True,
        which: str = 'stdout'
    ) -> bytes:
        """Internal byte read helper.

        Arguments:
            args: Arguments to the base executable.
            shell: Same as subprocess.run
            which: Read from a CompletedProcess' stderr or
                stdout attribute.
        Returns:
            Raw bytes from the from the CompletedProcess
            stdio attribute.
        """
        try:
            cmd = self._run_cmd_raw(*args, shell=shell, check=True)
        except subprocess.CalledProcessError as e:
            match e.returncode:
                case 127:
                    raise CommandNotFound(
                        f"Command for {e.args!r} not found"
                    ) from e
                case _:
                    raise e
        _bytes = getattr(cmd, which)
        return _bytes

    def _run_cmd_read_str(
        self,
        *args: str,
        shell: bool = True,
        which: str = 'stdout',
        encoding: str = UTF8,
    ) -> str:
        """Internal string read helper.

        Arguments:
            args: Arguments to the base executable.
            shell: Same as subprocess.run
            encoding: A valid bytes.decode() encoding.
            which: Read from a CompletedProcess' stderr or
                stdout attribute.
        Returns:
            A decoded string from the named CompltedProcess
            stdio attribute.
        """
        stdio_bytes = self._run_cmd_read_bytes(
            *args, shell=shell, which = which)
        decoded = stdio_bytes.decode(encoding=encoding)

        return decoded

    def read_as_bytesio(
        self,
        *args: str,
        shell: bool = True,
        which: str= 'stdout',
    ) -> BytesIO:
        """Call `base_command with `args`, get output as a new io.BytesIO.

        The BytesIO will seeks to zero after initial write
        to help use PIL.Image.open and similar functions.

        Arguments:
            args: Arguments to the base executable.
            shell: Same as subprocess.run
            which: Read from a CompletedProcess' stderr or
                stdout attribute.
        Returns:
            An io.BytesIO string from the named CompletedProcess
            stdio attribute.
        """
        raw = self._run_cmd_read_bytes(
            *args, shell=shell, which=which)
        s = BytesIO(raw)
        s.seek(0)

        return s

    def read_as_stringio(
        self,
        *args: str,
        shell: bool = True,
        which: str = 'stdout',
        encoding: str = UTF8,
        newline: str = '\n'
    ) -> StringIO:
        """Call `base_command with `args`, get output as a new io.StringIO.

        The StringIO will seek to zero after initial write
        to help use csv.reader, json.load, and similar tools.

        Arguments:
            args: Arguments to the base executable.
            shell: Same as subprocess.run
            which: Read from a CompletedProcess' stderr or
                stdout attribute.
            encoding: A valid bytes.decode() encoding.
            newline: Same as io.StringIO.
        Returns:
            An io.BytesIO string from the named CompletedProcess
            stdio attribute.
        """
        raw = self._run_cmd_read_str(
            *args, shell=shell, which=which, encoding=encoding)
        s = StringIO(raw, newline=newline)
        s.seek(0)

        return s


class PasteRunnerABC(BaseRunner, abc.ABC):
    """A template runner for reading the clipboard.

    This assumes the following:
    1. One main clipboard without alternates
    2. Multiple datatypes are possible at once

    Override the following to use the class:
    1. _fmt_read_mimetype_args
    2. list_types

    See WLPasteRunner for an example of how.

    Arguments:
        base_executable: A command name or path to an executable.
        version_parser: Reads a version object from a string.
        test_executable: Test the runner immediately on init.
    """


    @abc.abstractmethod
    def list_types(self) -> list[str]:
        """List mime types seen in the clipboard."""
        raise NotImplementedError("Abstract method")

    def test_executables(self) -> bool:
        if not self._detect_version():
            return False
        return isinstance(self.list_types(), list)

    @abc.abstractmethod
    def _fmt_read_mimetype_args(self, mime_type: str) -> tuple[str, ...]:
        """Get a series of commands to read a specific MIME type."""
        raise NotImplementedError("Abstract method")

    def read_mime_as_bytes(self, mime_type: str) -> bytes:
        args = self._fmt_read_mimetype_args(mime_type=mime_type)
        return self._run_cmd_read_bytes(*args)

    def read_mime_as_str(self, mime_type: str, encoding: str = UTF8) -> str:
        _bytes = self.read_mime_as_bytes(mime_type=mime_type)
        _str = _bytes.decode(encoding=encoding)
        return _str

    @contextmanager
    def open_mime_as_bytesio(
        self,
        mime_type: str
    ) -> Generator[BytesIO, None, None]:
        args = self._fmt_read_mimetype_args(mime_type=mime_type)
        s = self.read_as_bytesio(*args)
        yield s

    @contextmanager
    def open_mime_as_stringio(
        self,
        mime_type: str
    ) -> Generator[StringIO, None, None]:
        args = self._fmt_read_mimetype_args(mime_type=mime_type)
        s = self.read_as_stringio(*args)
        yield s


class RunnerWithDefault(BaseRunner):

    default_executable: ClassVar[str]

    def __init__(
        self,
        override_executable: str | Path | None = None,
        parse_version: _Converter[str, str] | None = None,
        test_executables: bool = True,
    ):
        super().__init__(
            executable=override_executable or self.default_executable,
            version_parser=parse_version,
            test_executables=test_executables
        )


class WLPasteRunner(RunnerWithDefault, PasteRunnerABC):
    """Wraps wl-paste from wl-clipboard.

    Arguments:
        base_executable: The wl-paste executable name or path.
        version_parser: Reads a version object from a string.
        test_executable: Test the runner immediately on init.
    """

    default_executable = "wl-paste"

    def __init__(
        self,
        override_executable: str | Path | None = None,
        parse_version: _Converter[str, str] = parse_version_prefixed,
        test_executables: bool = True,
    ):
        super().__init__(
            override_executable=override_executable or self.default_executable,
            parse_version=parse_version,
            test_executables=test_executables)

    def _fmt_read_mimetype_args(self, mime_type: str) -> tuple[str, ...]:
        return '--type', f"\"{mime_type}\""

    def list_types(self) -> list[str]:
        try:
            r = self._run_cmd_read_str('--list-types')
        except subprocess.CalledProcessError as e:
            first_line_raw: bytes = e.stderr.split(b'\n', 1)[0]
            first_line = first_line_raw.decode(encoding=UTF8)
            raise RunnerException(first_line) from e
        return r.split()


class XClipPasteRunner(RunnerWithDefault, PasteRunnerABC):
    """Wraps xclip.

    Arguments:
        base_executable: The xclip executable name or path.
        version_parser: Reads a version object from a string.
        test_executable: Test the runner immediately on init.
    """
    version_on = StdioStream.STDERR
    default_executable = 'xclip'

    def __init__(
        self,
        override_executable: str | Path | None = None,
        parse_version: _Converter[str, str] = parse_version_prefixed,
        test_executables: bool = True,
    ):
        super().__init__(
            override_executable=override_executable,
            parse_version=parse_version,
            test_executables=test_executables)

    def _get_flags_for_version_check(self) -> tuple[str, ...]:
        return ('-version',)

    def _fmt_read_mimetype_args(self, mime_type: str) -> tuple[str, ...]:
        return '-o', '-selection', 'clipboard', '-t', f"\"{mime_type}\""

    def list_types(self) -> list[str]:
        try:
            r = self._run_cmd_read_str('-o', '-selection', 'clipboard', '-t', 'TARGETS')
        except subprocess.CalledProcessError as e:
            raise RunnerException.from_called_process_error(e)
        types = [v for v in r.split() if not v.isupper()]
        return types


class _MacOSSwversionRunner(BaseRunner):
    """Wraps the OS sw_version built-in for pbpaste and osascript."""

    def __init__(
            self, base_executable: str | Path ='sw_version',
            version_parser: _Converter[str, str] = parse_mac_version,
            test_executables: bool = True
        ):
            super().__init__(base_executable, version_parser, test_executables)

    def _get_flags_for_version_check(self) -> tuple[str, ...]:
        return tuple()

_MACOS_SW_VERSION_RUNNER: _MacOSSwversionRunner | None = None


def _get_mac_os_version() -> str | None:
    global _MACOS_SW_VERSION_RUNNER
    if _MACOS_SW_VERSION_RUNNER is None:
        _MACOS_SW_VERSION_RUNNER = _MacOSSwversionRunner()
    return _MACOS_SW_VERSION_RUNNER.version


class MacPbpastePasterunner(RunnerWithDefault, PasteRunnerABC):
    """Limited stub data paste runner which only supports ASCII text.

    That may also be broken.
    """
    default_executable = 'pbpaste'
    def __init__(
            self, override_executable: str | Path | None = None,
            test_executables: bool = True
    ):
        super().__init__(
            override_executable=override_executable, parse_version=None, test_executables=test_executables)

    def _detect_version(self) -> bool:
        self._version = _get_mac_os_version()
        return True

    def list_types(self) -> list[str]:
        """Kind of a lie for now since rich text may be returned.

        Let's see what happens anyway."""
        return ["text/plain"]

    def test_executables(self) -> bool:
        return self._detect_version()

    def _fmt_read_mimetype_args(self, mime_type: str) -> tuple[str, ...]:
        if mime_type != 'text/plain':
            raise NotImplementedError(f"Support for non-ASCII text unimplemented.")
        return ('-Prefer', 'ascii')


def _get_stdio_stream(mode: str):
    """Prevents pytest's monkeypatch fixture to avoid breaking pytest.

    https://docs.pytest.org/en/stable/how-to/monkeypatch.html#global-patch-example-preventing-requests-from-remote-operations
    """
    match mode:
        case 'w':
            return sys.stdout
        case 'wt':
            return sys.stdout
        case 'wb':
            return sys.stdout.buffer
        case 't':
            return sys.stdin
        case 'r':
            return sys.stdin
        case 'rb':
            return sys.stdin.buffer
        case _:
            return None


_open = open
"""Prevents pytest's monkeypatch fixture to avoid breaking pytest.

https://docs.pytest.org/en/stable/how-to/monkeypatch.html#global-patch-example-preventing-requests-from-remote-operations
"""


@contextmanager
def open_stdio(path: str | Path, mode: str = "r"):
    """Wraps `open()` by opening `'-'` as standard io streams.

    ```py
    from your_module import get_markdown

    def save_markdown(destination: str | Path):
        data = get_markdown()
        with open(destination) as f:
            f.write(data)
    ```

    Arguments:
        path: Either a path or `'-'` as a string.
        mode: `"w"`, `'wt'`, `'wb'`, `'r'`, `'rt'`, or `'rb'`.
    Returns:
        A context manager for a file or standard output.
    """
    if not isinstance(mode, str):
        raise TypeError("mode must be a string")

    if path == "-":
        stream = _get_stdio_stream(mode)
        if not stream:
            raise ValueError("only 'w' and 'wb' allowed.")
        else:
            yield stream
    else:
        with _open(path, mode) as out:
            yield out


def paste_data_type_to_path_or_stdout[V](
    runner: PasteRunnerABC,
    path: str | Path,
    data_type: str,
    mode: str = "w"
) -> None:
    """Attempt to use a given runner to retrieve given mime types.

    Arguments:
        runner: A paste runner.
        path: A path to a file or - to write to stdout.
        data_type: A platform-dependent string.
        mode: `'w'`, `'wt'`, or `'wb'`.
    """
    with ExitStack() as ctx:
        # Keep this first to check for invalid mode strings
        # before running any slow subprocess calls
        destination = ctx.enter_context(
            open_stdio(path, mode=mode))
        if "b" in mode:
            source = ctx.enter_context(
                runner.open_mime_as_bytesio(mime_type=data_type))
        else:
            source = ctx.enter_context(
                runner.open_mime_as_stringio(mime_type=data_type))
        data = source.read()
        destination.write(data) # type: ignore


@dataclass(frozen=True)
class _RunnerCriteria:
    platform: str | None = None
    session_type: str | None = None

    @classmethod
    def from_os(cls):
        return cls(
            platform=sys.platform,
            session_type=os.environ.get('XDG_SESSION_TYPE', None)
        )

    def __str__(self):
        parts=[f"{k}={v!r}" for k,v in asdict(self)]
        return ", ".join(parts)


RUNNERS: dict[_RunnerCriteria, type[RunnerWithDefault]] = {
   _RunnerCriteria(platform='darwin'): MacPbpastePasterunner,
   _RunnerCriteria(session_type='wayland'): WLPasteRunner,
   _RunnerCriteria(session_type='x11'): XClipPasteRunner
}


def get_platform_paste_runner_type() -> RunnerWithDefault:
    """Gets an instance of the default platform runner.

    For Linux and BSDs, this depends on whether you use
    Wayland or X11 as your display system. On macOS, the
    only implemented runner is
    """
    _system = _RunnerCriteria.from_os()
    have_runner = RUNNERS.get(_system, None)
    if have_runner is None:
        raise NotImplementedError(f"No built-in support for {_system}")
    else:
        return have_runner()


def paste_from_clipboard(
    runner: PasteRunnerABC,
    mime_types: str | Iterable[str],
    destination: str | Path = "-",
):
    if isinstance(mime_types, str):
        mime_types = (mime_types, )
    else:
        mime_types = tuple(mime_types)
    available_types = set(runner.list_types())
    if not available_types:
        raise EmptyClipboardException(f"Clipboard empty!")
    matching_types = [t for t in mime_types if t in available_types]
    if not matching_types:
        raise NoMatchingClipboardData(f"No types matching any of {', '.join([repr(m) for m in mime_types])}")

    paste_data_type_to_path_or_stdout(
        runner=runner,
        path=destination,
        data_type=matching_types[0]
    )


class ClipboardActionEnum(StrEnum):

    # StrEnum needs docstring help on some Python versions
    def __new__(cls, value, doc=None):
        as_cli = value.replace('_', '-')
        self = str.__new__(cls, as_cli)
        self._value_ = as_cli
        if doc:
            self.__doc__ = doc
        return self

    PASTE = auto(), """Paste from the clipboard to a file or stdout (-)."""

    LIST_TYPES = auto(), """List available data types as strings. The results are platform dependent."""

    GET_BACKEND = auto(), """Report the backend detected."""

    # COPY = auto()
    # """Copy values from stdin (-) or a path."""


class LogLevelAction(argparse.Action):
    """Gets a logging.INFO-like value from an argparser argument."""

    def __init__(self, option_strings, dest, nargs=None, **kwargs):
        if nargs is not None:
            raise ValueError("nargs not allowed")
        super().__init__(option_strings, dest, **kwargs)

    def __call__(self, parser, namespace, values, option_string=None):
        value: str = getattr(namespace, self.dest)
        try:
            level = int(value)
            if level < 0:
                raise ValueError(f"Cannot have negative log levels")
        except ValueError as _:
            upper = value.upper()
            level = getattr(logging, upper, None)
            if level is None:
                raise ValueError(f"Unknown logging level {value!r}. Hint: try DEBUG")
        setattr(namespace, self.dest, level)


def _build_parser() -> argparse.ArgumentParser:
    # Lazy way around subparser complexity
    def _add_log_level(_parser):
        _parser.add_argument(
            '-v', '--log-level', default=logging.INFO, action=LogLevelAction,
            help="Logging level as a Python named level (INFO, etc.) or an integer")
        return _parser

    parser = _add_log_level(argparse.ArgumentParser(prog='cwip'))
    subparsers = parser.add_subparsers(dest='action')


    def _build_subparser(action: StrEnum, *args, **kwargs):
        # Use docstring if it exists, the help="keyword argument", or None
        member = action.__class__.__members__[action.name]
        action_docstring = getattr(member, '__doc__', None)
        help_text=kwargs.get('help', action_docstring)

        plain_action: str = action
        subparser = subparsers.add_parser(
            plain_action, *args, help=help_text, **kwargs)

        return _add_log_level(subparser)

    # copy is unimplemented for now
    _ = _build_subparser(ClipboardActionEnum.LIST_TYPES)
    _ = _build_subparser(ClipboardActionEnum.GET_BACKEND)

    paste = _build_subparser(ClipboardActionEnum.PASTE)
    paste.add_argument(
        "path", type=str,
        help="The path to paste to or - for stdout.""")
    paste.add_argument(
        "--type", "-t", type=str, nargs="+", required=True,
        help="A data type to paste. On Linux, this should be a MIME type string."""
    )

    return parser


def main():
    parser = _build_parser()
    args = parser.parse_args()

    log: logging.Logger | logging.LoggerAdapter
    logging.basicConfig(level=args.log_level)
    log = logging.getLogger("cwip")

    non_zero_exit = None
    action = args.action

    if action is None:
        parser.print_help(file=sys.stderr)
        non_zero_exit=1
    else:
        try:
            runner_type = get_platform_paste_runner_type()
            runner = runner_type()  # type: ignore
            match action:
                case ClipboardActionEnum.GET_BACKEND:
                    print(f"{runner.base_executable} {runner.version}")
                case ClipboardActionEnum.LIST_TYPES:
                    for type in runner.list_types():
                        print(type)
                case ClipboardActionEnum.PASTE:
                    paste_from_clipboard(
                        runner=runner, mime_types=args.type, destination=args.path)
                case _:
                    log.error(f"{args.action!r} not supported! try --help")
                    non_zero_exit = 1

        except RunnerException as e:
            log.error(f"{e.args[0]}")
            log.debug(e.__cause__)
            non_zero_exit = 1

    if non_zero_exit is not None:
        exit(code=non_zero_exit)


if __name__ == "__main__":
    main()
