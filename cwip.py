import abc
import argparse
import logging
import os
import re
import subprocess
import sys


from contextlib import ExitStack, contextmanager
from enum import StrEnum, auto
from io import BytesIO, StringIO
from pathlib import Path
from typing import Final, Generator, Generic, Hashable, Iterable, NamedTuple, Protocol, Self, TypeVar


__all__ = [
    'DEV_NULL',
    'UTF8',
    'MajorMinorPatchVersion',
    'RunnerException',
    'NoVersionFound',
    'BaseRunner',
    'BasePasteRunner',
    'EmptyClipboardException',
    'WLPasteRunner',
    'get_platform_default_paste_runner',
    'paste_from_clipboard'
]


H = TypeVar('H', bound=Hashable, covariant=True)
"""Version data as hashable to permit O(1) checks.

This does not include comparison because hashed-based
versioning might lack a clear ordering.
"""


class MajorMinorPatchVersion(NamedTuple):
    """A version following Major, Minor, Patch, Extra.

    This is not the only way to version applications.
    Other variations include:
    - Git-based hashes for commits
    - Date-based releases (Minecraft, JetBrains, etc)

    """
    major: int
    minor: int = 0
    patch: int = 0
    extra: str | None = None
    """For 3.1rc as in release candidates, etc"""

    def __str__(self) -> str:
        return ".".join((str(s) for s in self))


_VERSION_PATTERN = re.compile(r"""
(?P<major>[0-9]+)
(?:
   \.(?P<minor>[0-9]+)
   (?:
      \.(?P<patch>[0-9])
   )?
)?
(?P<extra>[^0-9][a-zA-Z0-9]*)?
""", re.X)


def parse_version(
    raw: str,
) -> MajorMinorPatchVersion:
    """Parse a `raw` A.B.Cd pattern as a Version instance.

    It raises a ValueErorr if it fails to match VERSION_PATTERN.

    Arguments:
        raw: a raw string.

    Returns:
        A Version instance.
    """
    match = _VERSION_PATTERN.match(raw)
    if not match:
        raise ValueError(f"{raw=!r} does not match {_VERSION_PATTERN!r}")
    match_strings = match.groupdict()
    args = dict()
    # No match if there's no major version
    for name in ('major', 'minor', 'patch'):
        if name not in match_strings:
            break
        value = int(match_strings[name])
        args[name] = value
    if 'extra' in match_strings:
        args['extra'] = match_strings['extra']
    return MajorMinorPatchVersion(**args)


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
    parser: _Converter[str, V] = parse_version
) -> V:
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


class BaseRunner(Generic[H]):
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

    _version: H | None = None
    _version_parser: _Converter[str, H] | None

    @property
    def base_executable(self) -> str:
        return self._base_executable

    @property
    def version(self) -> H | None:
        return self._version

    def __init__(
        self,
        base_executable: str,
        version_parser: _Converter[str, H] | None = None,
        test_executables: bool = True
    ):
        super().__init__()
        if not isinstance(base_executable, str):
            raise TypeError(f"{base_executable=!r} is not a string")
        self._base_executable: str = base_executable
        if not callable(version_parser):
            raise TypeError(f"{version_parser=!r} is not callable")
        self._version_parser = version_parser
        if test_executables:
            self.test_executables()

    def _get_flags_for_version_check(self) -> tuple[str, ...]:
        return _VERSION_ARGS

    def _set_version_from_stdio(self, which: str = 'stdout') -> bool:
        args = self._get_flags_for_version_check()
        success: bool = False
        utf8 = None
        try:
            utf8 = self._run_cmd_read_str(*args, which=which)
            version = self._parse_version(utf8)
            success = True
        except Exception as e:
            if utf8:
                line = utf8 if len(utf8) < 20 else repr(f"{utf8[:20]}...")
                msg = f"Failed to find a version from output {line}"
            else:
                msg = f"Failed to run {self._base_executable} with {args=!r}"
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
        """
        return self._set_version_from_stdio(which='stdout')

    def _parse_version(self, raw: str) -> H:
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
        parts = [self._base_executable, *args]
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
        cmd = self._run_cmd_raw(*args, shell=shell)
        if cmd.returncode != 0:
            raise subprocess.CalledProcessError(
                cmd.returncode, cmd=cmd.args, output=cmd.stdout, stderr=cmd.stderr)
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
        stdout_bytes = self._run_cmd_read_bytes(
            *args, shell=shell, which = which)
        stdout = stdout_bytes.decode(encoding=encoding)

        return stdout

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


class BasePasteRunner(BaseRunner[H], abc.ABC):
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

    def __init__(
        self,
        base_executable: str,
        parse_version: _Converter[str, H] | None = None,
        test_executables: bool = True,
    ):
        super().__init__(
            base_executable=base_executable,
            version_parser=parse_version,
            test_executables=test_executables
        )

    @abc.abstractmethod
    def list_types(self) -> list[str]:
        """List mime types seen in the clipboard."""
        raise NotImplementedError("Abstract method")

    def test_executables(self) -> bool:
        if not super().test_executables():
            return False
        try:
            self.list_types()
        except subprocess.CalledProcessError as _:
            return False
        return True

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


class WLPasteRunner(BasePasteRunner[H]):
    """Wraps wl-paste from wl-clipboard.

    Arguments:
        base_executable: The wl-paste executable name or path.
        version_parser: Reads a version object from a string.
        test_executable: Test the runner immediately on init.
    """

    def __init__(
        self,
        base_executable: str = 'wl-paste',
        parse_version: _Converter[str, H] = parse_version_prefixed,
        test_executables: bool = True,
    ):
        super().__init__(
            base_executable=base_executable,
            parse_version=parse_version,
            test_executables=test_executables)

    def _fmt_read_mimetype_args(self, mime_type: str) -> tuple[str, ...]:
        return '--type', f"\"{mime_type}\""

    def list_types(self) -> list[str]:
        try:
            r = self._run_cmd_read_str('--list-types')
        except subprocess.CalledProcessError as e:
            raise RunnerException.from_called_process_error(e)
        return r.split()


@contextmanager
def open_stdout(path: str | Path, mode: str = "w"):
    """Wraps `open()` by opening `'-'` as the standard output stream.

    ```py
    from your_module import get_markdown

    def save_markdown(destination: str | Path):
        data = get_markdown()
        with open(destination) as f:
            f.write(data)
    ```

    Arguments:
        path: Either a path or `'-'` as a string.
        mode: `"w"` or `'wb'`
    Returns:
        A context manager for a file or standard output.
    """
    if mode not in ('w', 'wb'):
        if isinstance(mode, str):
            problem = ValueError
        else:
            problem = TypeError
        raise problem("only 'w' and 'wb' allowed.")
    elif path == "-":
        if 'b' in mode:
            yield sys.stdout.buffer
        else:
            yield sys.stdout
    else:
        with open(path, mode) as out:
            yield out


def write_mime_type_to_path_or_stdout[V](
    runner: BasePasteRunner[V],
    path: str | Path,
    data_type: str,
    mode: str = "w"
) -> None:
    """Attempt to use a given runner to retrieve given mime types.

    Arguments:
        runner: A paste runner.
        path: A path to a file or - to write to stdout.
        data_type: A platform-dependent string.
        mode: Either `'w'` or `'wb'`.
    """
    with ExitStack() as ctx:
        # Keep this first to check for invalid mode strings
        # before running any slow subprocess calls
        destination = ctx.enter_context(
            open_stdout(path, mode=mode))
        if "b" in mode:
            source = ctx.enter_context(
                runner.open_mime_as_bytesio(mime_type=data_type))
        else:
            source = ctx.enter_context(
                runner.open_mime_as_stringio(mime_type=data_type))
        data = source.read()
        destination.write(data) # type: ignore


def get_platform_default_paste_runner() -> BasePasteRunner:
    platform = sys.platform
    session_type = os.environ.get('XDG_SESSION_TYPE', None)

    match (platform, session_type):
        case (_, 'wayland'):
            return WLPasteRunner()
        case (_, _):
            parts = [f"{platform=!r}"]
            if session_type:
                parts.append(f"{session_type=!r}")
            session_info = ", ".join(parts)
            raise NotImplementedError(f"No built-in support for {session_info}")


def paste_from_clipboard(
    runner: BasePasteRunner,
    mime_types: str | Iterable[str],
    destination: str | Path = "-",
):
    if isinstance(mime_types, str):
        mime_types = [mime_types]
    available_types = set(runner.list_types())
    if not available_types:
        raise EmptyClipboardException(f"Clipboard empty!")
    matching_types = [t for t in mime_types if t in available_types]
    if not matching_types:
        raise NoMatchingClipboardData(f"No types matching those provided")

    write_mime_type_to_path_or_stdout(
        runner=runner,
        path=destination,
        data_type=matching_types[0]
    )


class ClipboardAction(StrEnum):

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
    _ = _build_subparser(ClipboardAction.LIST_TYPES)
    _ = _build_subparser(ClipboardAction.GET_BACKEND)

    paste = _build_subparser(ClipboardAction.PASTE)
    paste.add_argument(
        "path", type=str,
        help="The path to paste to or - for stdout.""")
    paste.add_argument(
        "--type", "-t", type=str, nargs="+",
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
            runner = get_platform_default_paste_runner()
            match action:
                case ClipboardAction.GET_BACKEND:
                    print(f"{runner.base_executable} {runner.version}")
                case ClipboardAction.LIST_TYPES:
                    for type in runner.list_types():
                        print(type)
                case ClipboardAction.PASTE:
                    paste_from_clipboard(
                        runner=runner, mime_types=args.type, destination=args.path)
                case _:
                    log.error(f"{args.action!r} not supported! try --help")
                    non_zero_exit = 1

        except RunnerException as e:
            log.error(e)
            log.debug(e.__cause__)
            non_zero_exit = 1

    if non_zero_exit is not None:
        exit(code=non_zero_exit)


if __name__ == "__main__":
    main()
