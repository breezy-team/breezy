# Copyright (C) 2006-2011 Canonical Ltd
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

"""bisect command implementations."""

import sys

from . import revision as _mod_revision
from .commands import Command
from .controldir import ControlDir
from .errors import CommandError
from .option import Option
from .trace import note

BISECT_INFO_PATH = "bisect"
BISECT_REV_PATH = "bisect_revid"


class BisectCurrent:
    """Bisect class for managing the current revision."""

    def __init__(self, controldir, filename=BISECT_REV_PATH):
        """Initialize the BisectCurrent object.

        Args:
            controldir: The control directory for the tree.
            filename: The filename to store the current bisect revision id.
        """
        self._filename = filename
        self._controldir = controldir
        self._branch = self._controldir.open_branch()
        if self._controldir.control_transport.has(filename):
            self._revid = self._controldir.control_transport.get_bytes(filename).strip()
        else:
            self._revid = self._branch.last_revision()

    def _save(self):
        """Save the current revision."""
        self._controldir.control_transport.put_bytes(
            self._filename, self._revid + b"\n"
        )

    def get_current_revid(self):
        """Return the current revision id."""
        return self._revid

    def get_current_revno(self):
        """Return the current revision number as a tuple."""
        return self._branch.revision_id_to_dotted_revno(self._revid)

    def get_parent_revids(self):
        """Return the IDs of the current revision's predecessors."""
        repo = self._branch.repository
        with repo.lock_read():
            retval = repo.get_parent_map([self._revid]).get(self._revid, None)
        return retval

    def is_merge_point(self):
        """Is the current revision a merge point?"""
        return len(self.get_parent_revids()) > 1

    def show_rev_log(self, outf):
        """Write the current revision's log entry to a file."""
        rev = self._branch.repository.get_revision(self._revid)
        revno = ".".join([str(x) for x in self.get_current_revno()])
        outf.write(f"On revision {revno} ({rev.revision_id}):\n{rev.message}\n")

    def switch(self, revid):
        """Switch the current revision to the given revid."""
        working = self._controldir.open_workingtree()
        if isinstance(revid, int):
            revid = self._branch.get_rev_id(revid)
        elif isinstance(revid, list):
            revid = revid[0].in_history(working.branch).rev_id
        working.revert(None, working.branch.repository.revision_tree(revid), False)
        self._revid = revid
        self._save()

    def reset(self):
        """Revert bisection, setting the working tree to normal."""
        working = self._controldir.open_workingtree()
        last_rev = working.branch.last_revision()
        rev_tree = working.branch.repository.revision_tree(last_rev)
        working.revert(None, rev_tree, False)
        if self._controldir.control_transport.has(BISECT_REV_PATH):
            self._controldir.control_transport.delete(BISECT_REV_PATH)


class BisectLog:
    """Bisect log file handler."""

    def __init__(self, controldir, filename=BISECT_INFO_PATH):
        """Initialize the BisectLog object.

        Args:
            controldir: The control directory for the tree.
            filename: The filename to store the bisect log.
        """
        self._items = []
        self._current = BisectCurrent(controldir)
        self._controldir = controldir
        self._branch = None
        self._high_revid = None
        self._low_revid = None
        self._middle_revid = None
        self._filename = filename
        self.load()

    def _open_for_read(self):
        """Open log file for reading."""
        if self._filename:
            return self._controldir.control_transport.get(self._filename)
        else:
            return sys.stdin

    def _load_tree(self):
        """Load bzr information."""
        if not self._branch:
            self._branch = self._controldir.open_branch()

    def _find_range_and_middle(self, branch_last_rev=None):
        """Find the current revision range, and the midpoint."""
        self._load_tree()
        self._middle_revid = None

        if not branch_last_rev:
            last_revid = self._branch.last_revision()
        else:
            last_revid = branch_last_rev

        repo = self._branch.repository
        with repo.lock_read():
            graph = repo.get_graph()
            rev_sequence = graph.iter_lefthand_ancestry(
                last_revid, (_mod_revision.NULL_REVISION,)
            )
            high_revid = None
            low_revid = None
            between_revs = []
            for revision in rev_sequence:
                between_revs.insert(0, revision)
                matches = [
                    x[1]
                    for x in self._items
                    if x[0] == revision and x[1] in ("yes", "no")
                ]
                if not matches:
                    continue
                if len(matches) > 1:
                    raise RuntimeError(f"revision {revision} duplicated")
                if matches[0] == "yes":
                    high_revid = revision
                    between_revs = []
                elif matches[0] == "no":
                    low_revid = revision
                    del between_revs[0]
                    break

            if not high_revid:
                high_revid = last_revid
            if not low_revid:
                low_revid = self._branch.get_rev_id(1)

        # The spread must include the high revision, to bias
        # odd numbers of intervening revisions towards the high
        # side.

        spread = len(between_revs) + 1
        middle_index = 0 if spread < 2 else spread // 2 - 1

        if len(between_revs) > 0:
            self._middle_revid = between_revs[middle_index]
        else:
            self._middle_revid = high_revid

        self._high_revid = high_revid
        self._low_revid = low_revid

    def _switch_wc_to_revno(self, revno, outf):
        """Move the working tree to the given revno."""
        self._current.switch(revno)
        self._current.show_rev_log(outf=outf)

    def _set_status(self, revid, status):
        """Set the bisect status for the given revid."""
        if not self.is_done():
            if status != "done" and revid in [
                x[0] for x in self._items if x[1] in ["yes", "no"]
            ]:
                raise RuntimeError(f"attempting to add revid {revid} twice")
            self._items.append((revid, status))

    def change_file_name(self, filename):
        """Switch log files."""
        self._filename = filename

    def load(self):
        """Load the bisection log."""
        self._items = []
        if self._controldir.control_transport.has(self._filename):
            revlog = self._open_for_read()
            for line in revlog:
                (revid, status) = line.split()
                self._items.append((revid, status.decode("ascii")))

    def save(self):
        """Save the bisection log."""
        contents = b"".join(
            (b"%s %s\n" % (revid, status.encode("ascii")))
            for (revid, status) in self._items
        )
        if self._filename:
            self._controldir.control_transport.put_bytes(self._filename, contents)
        else:
            sys.stdout.write(contents)

    def is_done(self):
        """Report whether we've found the right revision."""
        return len(self._items) > 0 and self._items[-1][1] == "done"

    def set_status_from_revspec(self, revspec, status):
        """Set the bisection status for the revision in revspec."""
        self._load_tree()
        revid = revspec[0].in_history(self._branch).rev_id
        self._set_status(revid, status)

    def set_current(self, status):
        """Set the current revision to the given bisection status."""
        self._set_status(self._current.get_current_revid(), status)

    def is_merge_point(self, revid):
        """Check if the given revision is a merge point.

        Args:
            revid: The revision id to check.

        Returns:
            True if the revision has more than one parent, False otherwise.
        """
        return len(self.get_parent_revids(revid)) > 1

    def get_parent_revids(self, revid):
        """Get the parent revision IDs for a given revision.

        Args:
            revid: The revision id to get parents for.

        Returns:
            List of parent revision IDs, or None if not found.
        """
        repo = self._branch.repository
        with repo.lock_read():
            retval = repo.get_parent_map([revid]).get(revid, None)
        return retval

    def bisect(self, outf):
        """Using the current revision's status, do a bisection."""
        self._find_range_and_middle()
        # If we've found the "final" revision, check for a
        # merge point.
        while (
            self._middle_revid == self._high_revid
            or self._middle_revid == self._low_revid
        ) and self.is_merge_point(self._middle_revid):
            for parent in self.get_parent_revids(self._middle_revid):
                if parent == self._low_revid:
                    continue
                else:
                    self._find_range_and_middle(parent)
                    break
        self._switch_wc_to_revno(self._middle_revid, outf)
        if (
            self._middle_revid == self._high_revid
            or self._middle_revid == self._low_revid
        ):
            self.set_current("done")


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

    brz bisect start
        Start a bisect, possibly clearing out a previous bisect.

    brz bisect yes [-r rev]
        The specified revision (or the current revision, if not given)
        has the characteristic we're looking for,

    brz bisect no [-r rev]
        The specified revision (or the current revision, if not given)
        does not have the characteristic we're looking for,

    brz bisect move -r rev
        Switch to a different revision manually.  Use if the bisect
        algorithm chooses a revision that is not suitable.  Try to
        move as little as possible.

    brz bisect reset
        Clear out a bisection in progress.

    brz bisect log [-o file]
        Output a log of the current bisection to standard output, or
        to the specified file.

    brz bisect replay <logfile>
        Replay a previously-saved bisect log, forgetting any bisection
        that might be in progress.

    brz bisect run <script>
        Bisect automatically using <script> to determine 'yes' or 'no'.
        <script> should exit with:
           0 for yes
           125 for unknown (like build failed so we could not test)
           anything else for no
    """

    takes_args = ["subcommand", "args*"]
    takes_options = [
        Option("output", short_name="o", help="Write log to this file.", type=str),
        "revision",
        "directory",
    ]

    def _check(self, controldir):
        """Check preconditions for most operations to work."""
        if not controldir.control_transport.has(BISECT_INFO_PATH):
            raise CommandError("No bisection in progress.")

    def _set_state(self, controldir, revspec, state):
        """Set the state of the given revspec and bisecting.

        Returns boolean indicating if bisection is done.
        """
        bisect_log = BisectLog(controldir)
        if bisect_log.is_done():
            note("No further bisection is possible.\n")
            bisect_log._current.show_rev_log(outf=self.outf)
            return True

        if revspec:
            bisect_log.set_status_from_revspec(revspec, state)
        else:
            bisect_log.set_current(state)
        bisect_log.bisect(self.outf)
        bisect_log.save()
        return False

    def run(self, subcommand, args_list, directory=".", revision=None, output=None):
        """Handle the bisect command."""
        log_fn = None
        if subcommand in ("yes", "no", "move") and revision:
            pass
        elif subcommand in ("replay",) and args_list and len(args_list) == 1:
            log_fn = args_list[0]
        elif subcommand in ("move",) and not revision:
            raise CommandError("The 'bisect move' command requires a revision.")
        elif subcommand in ("run",):
            run_script = args_list[0]
        elif args_list or revision:
            raise CommandError("Improper arguments to bisect " + subcommand)

        controldir, _ = ControlDir.open_containing(directory)

        # Dispatch.
        if subcommand == "start":
            self.start(controldir)
        elif subcommand == "yes":
            self.yes(controldir, revision)
        elif subcommand == "no":
            self.no(controldir, revision)
        elif subcommand == "move":
            self.move(controldir, revision)
        elif subcommand == "reset":
            self.reset(controldir)
        elif subcommand == "log":
            self.log(controldir, output)
        elif subcommand == "replay":
            self.replay(controldir, log_fn)
        elif subcommand == "run":
            self.run_bisect(controldir, run_script)
        else:
            raise CommandError("Unknown bisect command: " + subcommand)

    def reset(self, controldir):
        """Reset the bisect state to no state."""
        self._check(controldir)
        BisectCurrent(controldir).reset()
        controldir.control_transport.delete(BISECT_INFO_PATH)

    def start(self, controldir):
        """Reset the bisect state, then prepare for a new bisection."""
        if controldir.control_transport.has(BISECT_INFO_PATH):
            BisectCurrent(controldir).reset()
            controldir.control_transport.delete(BISECT_INFO_PATH)

        bisect_log = BisectLog(controldir)
        bisect_log.set_current("start")
        bisect_log.save()

    def yes(self, controldir, revspec):
        """Mark that a given revision has the state we're looking for."""
        self._set_state(controldir, revspec, "yes")

    def no(self, controldir, revspec):
        """Mark a given revision as wrong."""
        self._set_state(controldir, revspec, "no")

    def move(self, controldir, revspec):
        """Move to a different revision manually."""
        current = BisectCurrent(controldir)
        current.switch(revspec)
        current.show_rev_log(outf=self.outf)

    def log(self, controldir, filename):
        """Write the current bisect log to a file."""
        self._check(controldir)
        bisect_log = BisectLog(controldir)
        bisect_log.change_file_name(filename)
        bisect_log.save()

    def replay(self, controldir, filename):
        """Apply the given log file to a clean state, so the state is
        exactly as it was when the log was saved.
        """
        if controldir.control_transport.has(BISECT_INFO_PATH):
            BisectCurrent(controldir).reset()
            controldir.control_transport.delete(BISECT_INFO_PATH)
        bisect_log = BisectLog(controldir, filename)
        bisect_log.change_file_name(BISECT_INFO_PATH)
        bisect_log.save()

        bisect_log.bisect(self.outf)

    def run_bisect(self, controldir, script):
        """Run automatic bisection using a script.

        Args:
            controldir: The control directory for the tree.
            script: Script path to run for testing each revision.
        """
        import subprocess

        note("Starting bisect.")
        self.start(controldir)
        while True:
            try:
                process = subprocess.Popen(script, shell=True)
                process.wait()
                retcode = process.returncode
                if retcode == 0:
                    done = self._set_state(controldir, None, "yes")
                elif retcode == 125:
                    break
                else:
                    done = self._set_state(controldir, None, "no")
                if done:
                    break
            except RuntimeError:
                break
