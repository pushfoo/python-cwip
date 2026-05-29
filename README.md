# cwip

Slop-free clipboard access in pure Python.

## Intended Audience

Currently, this this tool is limited to Linux users
and adventurous people on other Wayland environemtns.

For example, here are the current install instructions:

```shell
uv add "cwip @ git+https://github.com/pushfoo/python-cwip@main"
```

If you prefer pip, then use:

```shell
pip install git+https://github.com/pushfoo/python-cwip
```

## Features

| Clipboard Approach       | OS              | Paste from?      | Copy to?  |
|--------------------------|-----------------|------------------|-----------|
| Wayland (wl_data_device) | Linux, BSDs[^1] | Yes (`wl-paste`) | Soon      |
| X server clipboard       | Linux, BSDs[^2] | Yes (`xclip`)    | Soon      |
| Mac pbpaste (text only)  | macOS           | Soon             | Soon      |
| Mac osascript            | macOS           |                  |           |
| Win32 API                | Windows         |                  |           |

Direct API calls via ctypes will be bound if/when either of the
following arise:
- need
- human contributors

## Aims

### Anti-goals

These are things to avoid

1. Supporting too many clipboards on one system
2. Hard install dependencies, especially binaries
3. Riding hype trains into complexity

Needless async or use of LLMs is to be avoided. This library is
for getting things done instead of fighting your tools.

#### But I want those things!

Try [Arboard][]. It's pretty cool.

[Arboard]: https://github.com/1Password/arboard


### Goals

1. Aim for Pure Python and subprocess calls
2. Support non-text formats when feasible
3. Pythonic code ([context managers][], [streams][])

[context managers]: https://docs.python.org/3/library/contextlib.html#contextlib.contextmanager
[streams]: https://docs.python.org/3/library/io.html


## Why not cwip?

In addition to being slower than binary-backed alternatives,
there are further limitations for each platform.

### UI flashes on Wayland

Wayland clipboard access can cause "flashes" in UI taskbars.
This is an unavoidable consequence of Wayland's design:

1. Clipboard access requires a window
2. `wl-paste` creates one

### Limited support for "extra" X clipboards

Although X11 theoretically supports multiple named
clipboards, this project does not aim to support
them. [Arboard][] or another library is a better
fit for your purposes.

[^1]: See [UI flashes on Wayland](#ui-flashes-on-wayland).
[^2]: See [Limited support for "extra" X clipboards](#limited-support-for-extra-x-clipboards)