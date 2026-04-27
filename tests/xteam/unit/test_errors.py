from xteam_lib.errors import (
    EXIT_BAD_INPUT,
    EXIT_KB_UNREACHABLE,
    KBUnreachable,
    PRDInvalid,
    SnapshotCorrupt,
    XTeamError,
)


def test_exit_codes_are_stable_integers():
    assert EXIT_BAD_INPUT == 2
    assert EXIT_KB_UNREACHABLE == 3


def test_all_xteam_errors_inherit_base():
    assert issubclass(PRDInvalid, XTeamError)
    assert issubclass(KBUnreachable, XTeamError)
    assert issubclass(SnapshotCorrupt, XTeamError)


def test_error_carries_message_and_exit_code():
    err = PRDInvalid("missing field: goal")
    assert str(err) == "missing field: goal"
    assert err.exit_code == EXIT_BAD_INPUT

    err2 = KBUnreachable("mcp timeout")
    assert err2.exit_code == EXIT_KB_UNREACHABLE
