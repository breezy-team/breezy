import os
import bzrlib.tests
from bzrlib.commands import Command, register_command
from bzrlib.errors import BzrCommandError

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

    takes_args = ['subcommand', 'args*']

    def run(self, subcommand, args_list):
        # Handle subcommand parameters.

        revision = None
        log_fn = None
        if subcommand in ('yes', 'no') and args_list and len(args_list) == 2:
            if args_list[0] == "-r":
                revision = args_list[1]
            else:
                raise BzrCommandError("Improper arguments to bisect " + subcommand)
        elif subcommand in ('replay',) and args_list and len(args_list) == 1:
            log_fn = args_list[0]
        elif args_list:
            raise BzrCommandError("Improper arguments to bisect " + subcommand)

        # Dispatch.

        if subcommand == "start":
            self.start()
        elif subcommand == "yes":
            self.yes(revision)
        elif subcommand == "no":
            self.no(revision)
        elif subcommand == "reset":
            self.reset()
        elif subcommand == "log":
            self.log(None)
        elif subcommand == "replay":
            self.replay(log_fn)

    def reset(self):
        "Reset the bisect state to no state."
        pass

    def start(self):
        "Reset the bisect state, then prepare for a new bisection."
        pass

    def yes(self, revision):
        "Mark that a given revision has the state we're looking for."
        pass

    def no(self, revision):
        "Mark that a given revision does not have the state we're looking for."
        pass

    def log(self, filename):
        "Write the current bisect log to a file."
        pass

    def replay(self, filename):
        """Apply the given log file to a clean state, so the state is
        exactly as it was when the log was saved."""
        pass

register_command(cmd_bisect)

# Tests.

class BisectTests(bzrlib.tests.TestCaseWithTransport):
    def assertRevno(self, rev):
        "Make sure the revision number is as specified."

        revno = self.capture("revno")
        if ("%d" % rev) not in revno:
            raise AssertionError("not at revision %d" % rev)

    def setUp(self):
        bzrlib.tests.TestCaseWithTransport.setUp(self)

        self.tree = self.make_branch_and_tree(".")

        f = open("test_file", "w")
        f.write("one")
        f.close()
        self.tree.add(self.tree.relpath(os.path.join(os.getcwd(), 'test_file')))
        self.tree.commit(message = "add test file")

        file_contents = ["two", "three", "four", "five"]
        for content in file_contents:
            f = open("test_file", "w")
            f.write(content)
            f.close()
            self.tree.commit(message = "make test change")

    def testWorkflow(self):
        # Start up the bisection.  When the two ends are set, we should
        # end up in the middle.

        self.run_bzr('bisect', 'start')
        self.run_bzr('bisect', 'yes')
        self.run_bzr('bisect', 'no', '-r', '1')
        self.assertRevno(3)

        # Mark feature as present in the middle.  Should move us
        # halfway back between the current middle and the start.

        self.run_bzr('bisect', 'yes')
        self.assertRevno(2)

        # Mark feature as not present.  Since this is only one
        # rev back from the lowest marked revision with the feature,
        # the process should end, with the current rev set to the
        # rev following.

        self.run_bzr('bisect', 'no')
        self.assertRevno(3)

    def testReset(self):
        # Set up a bisection in progress.

        self.run_bzr('bisect', 'start')
        self.run_bzr('bisect', 'yes')
        self.run_bzr('bisect', 'no', '-r', '1')
        self.run_bzr('bisect', 'yes')
        self.assertRevno(2)

        # Now reset.

        self.run_bzr('bisect', 'reset')
        self.assertRevno(5)

    def testLog(self):
        # Set up a bisection in progress.

        self.run_bzr('bisect', 'start')
        self.run_bzr('bisect', 'yes')
        self.run_bzr('bisect', 'no', '-r', '1')
        self.run_bzr('bisect', 'yes')
        self.assertRevno(2)

        # Now save the log.

        log_data = self.capture('bisect', 'log')
        f = open("bisect_log", "w")
        f.write(log_data)
        f.close()

        # Reset and check.

        self.run_bzr('bisect', 'reset')
        self.assertRevno(5)

        # Read it back in.

        self.run_bzr('bisect', 'replay', 'bisect_log')
        self.assertRevno(2)

        # Mark another state, and see if the bisect moves in the
        # right way.

        self.run_bzr('bisect', 'no')
        self.assertRevno(3)

def test_suite():
    from bzrlib.tests.TestUtil import TestLoader
    return TestLoader().loadTestsFromTestCase(BisectTests)
