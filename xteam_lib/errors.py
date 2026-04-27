"""Exit codes and custom exceptions for xTeam.

Exit codes are stable (used by hooks/scripts to decide recovery actions).
Adding codes is backward-compatible; changing existing values is not.
"""

EXIT_BAD_INPUT = 2
EXIT_KB_UNREACHABLE = 3
EXIT_SNAPSHOT_CORRUPT = 4
EXIT_AGENT_FAILURE = 5


class XTeamError(Exception):
    exit_code = 1

    def __init__(self, message: str):
        super().__init__(message)


class PRDInvalid(XTeamError):
    exit_code = EXIT_BAD_INPUT


class KBUnreachable(XTeamError):
    exit_code = EXIT_KB_UNREACHABLE


class SnapshotCorrupt(XTeamError):
    exit_code = EXIT_SNAPSHOT_CORRUPT


class AgentFailure(XTeamError):
    exit_code = EXIT_AGENT_FAILURE
