from bzrlib.commands import Command, register_command

class cmd_bisect(Command):
    """Find an interesting commit using a binary search.

    Bisecting, in a nutshell, is a way to find the commit at which
    some testable change was made, such as the introduction of a bug
    or feature.  By identifying a version which did not have the
    interesting change and a later version which did, a developer
    can test for the presence of the change at various points in
    the history, eventually ending up at the precise commit when
    the change was first introduced.

    This command uses subcommands to implement the search, each
    of which changes the state of the bisection.  The
    subcommands are:

    bzr bisect start
        Start a bisect, possibly clearing out a previous bisect.

    bzr bisect yes [-r rev]
        The specified revision (or the current revision, if not given)
        has the characteristic we're looking for,

    bzr bisect no [-r rev]
        The specified revision (or the current revision, if not given)
        does not have the charactistic we're looking for,

    bzr bisect reset
        Clear out a bisection in progress.

    bzr bisect log
        Output a log of the current bisection to standard output.

    bzr bisect replay <logfile>
        Replay a previously-saved bisect log, forgetting any bisection
        that might be in progress.
"""

register_command(cmd_bisect)
