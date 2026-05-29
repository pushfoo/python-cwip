import pytest

from cwip import _build_parser, ClipboardAction

@pytest.fixture(params=[*ClipboardAction.__members__.values(), None])
def action(request):
    if have_enum := request.param:
        return have_enum.value
    else:
        return None


EXTRA_ARGS = {
    ClipboardAction.GET_BACKEND: tuple(),
    ClipboardAction.LIST_TYPES: tuple(),
    ClipboardAction.PASTE: ('-', '--type', 'text/plain'),
    None: tuple()
}

def test_log_level(action):
    if action:
        args = [action]
    else:
        args = []
    action_args = EXTRA_ARGS[action]
    if action_args:
        args.extend(action_args)
    args.extend(['--log-level', 'DEBUG'])

    parser = _build_parser()
    parsed = parser.parse_args(args)
    assert parsed.action == action
    assert parsed.log_level == 20
