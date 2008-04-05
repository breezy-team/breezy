# Copyright (C) 2008 Canonical Ltd
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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"Support for git-style bisection."

import sys
import os
import bzrlib.bzrdir
from bzrlib.commands import Command, register_command
from bzrlib.errors import BzrCommandError
from bzrlib.option import Option

from meta import *

bisect_info_path = ".bzr/bisect"
bisect_rev_path = ".bzr/bisect_revid"


class BisectCurrent(object):
    "Bisect class for managing the current revision."

    def __init__(self, filename = bisect_rev_path):
        self._filename = filename
        self._bzrdir = bzrlib.bzrdir.BzrDir.open_containing(".")[0]
        self._bzrbranch = self._bzrdir.open_branch()
        if os.path.exists(filename):
            revid_file = open(filename)
            self._revid = revid_file.read().strip()
            revid_file.close()
        else:
            self._revid = self._bzrbranch.last_revision()

    def _save(self):
        "Save the current revision."

        revid_file = open(self._filename, "w")
        revid_file.write(self._revid + "\n")
        revid_file.close()

    def get_current_revid(self):
        "Return the current revision id."
        return self._revid

    def get_current_revno(self):
        "Return the current revision number as a tuple."
        revdict = self._bzrbranch.get_revision_id_to_revno_map()
        return revdict[self.get_current_revid()]

    def get_parent_revids(self):
        "Return the IDs of the current revision's predecessors."
        repo = self._bzrbranch.repository
        repo.lock_read()
        retval = repo.get_parent_map([self._revid]).get(self._revid, None)
        repo.unlock()
        return retval

    def is_merge_point(self):
        "Is the current revision a merge point?"
        return len(self.get_parent_revids()) > 1

    def show_rev_log(self, out = sys.stdout):
        "Write the current revision's log entry to a file."
        rev = self._bzrbranch.repository.get_revision(self._revid)
        revno = ".".join([str(x) for x in self.get_current_revno()])
        out.write("On revision %s (%s):\n%s\n" % (revno, rev.revision_id,
                                                  rev.message))

    def switch(self, revid):
        "Switch the current revision to the given revid."
        working = self._bzrdir.open_workingtree()
        if isinstance(revid, int):
            revid = self._bzrbranch.get_rev_id(revid)
        elif isinstance(revid, list):
            revid = revid[0].in_history(working.branch).rev_id
        working.revert(None, working.branch.repository.revision_tree(revid),
                       False)
        self._revid = revid
        self._save()

    def reset(self):
        "Revert bisection, setting the working tree to normal."
        working = self._bzrdir.open_workingtree()
        last_rev = working.branch.last_revision()
        rev_tree = working.branch.repository.revision_tree(last_rev)
        working.revert(None, rev_tree, False)
        if os.path.exists(bisect_rev_path):
            os.unlink(bisect_rev_path)


class BisectLog(object):
    "Bisect log file handler."

    def __init__(self, filename = bisect_info_path):
        self._items = []
        self._current = BisectCurrent()
        self._bzrdir = None
        self._high_revid = None
        self._low_revid = None
        self._middle_revid = None
        self._filename = filename
        self.load()

    def _open_for_read(self):
        "Open log file for reading."
        if self._filename:
            return open(self._filename)
        else:
            return sys.stdin

    def _open_for_write(self):
        "Open log file for writing."
        if self._filename:
            return open(self._filename, "w")
        else:
            return sys.stdout

    def _load_bzr_tree(self):
        "Load bzr information."
        if not self._bzrdir:
            self._bzrdir = bzrlib.bzrdir.BzrDir.open_containing('.')[0]
            self._bzrbranch = self._bzrdir.open_branch()

    def _find_range_and_middle(self, branch_last_rev = None):
        "Find the current revision range, and the midpoint."
        self._load_bzr_tree()
        self._middle_revid = None

        if not branch_last_rev:
            last_revid = self._bzrbranch.last_revision()
        else:
            last_revid = branch_last_rev

        repo = self._bzrbranch.repository
        repo.lock_read()
        rev_sequence = repo.iter_reverse_revision_history(last_revid)
        high_revid = None
        low_revid = None
        between_revs = []
        for revision in rev_sequence:
            between_revs.insert(0, revision)
            matches = [x[1] for x in self._items
                       if x[0] == revision and x[1] in ('yes', 'no')]
            if not matches:
                continue
            if len(matches) > 1:
                raise RuntimeError("revision %s duplicated" % revision)
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
            low_revid = self._bzrbranch.get_rev_id(1)

        repo.unlock()

        # The spread must include the high revision, to bias
        # odd numbers of intervening revisions towards the high
        # side.

        spread = len(between_revs) + 1
        if spread < 2:
            middle_index = 0
        else:
            middle_index = (spread / 2) - 1

        if len(between_revs) > 0:
            self._middle_revid = between_revs[middle_index]
        else:
            self._middle_revid = high_revid

        self._high_revid = high_revid
        self._low_revid = low_revid

    def _switch_wc_to_revno(self, revno):
        "Move the working tree to the given revno."
        self._current.switch(revno)
        self._current.show_rev_log()

    def _set_status(self, revid, status):
        "Set the bisect status for the given revid."
        if not self.is_done():
            if status != "done" and revid in [x[0] for x in self._items 
                                              if x[1] in ['yes', 'no']]:
                raise RuntimeError("attempting to add revid %s twice" % revid)
            self._items.append((revid, status))

    def change_file_name(self, filename):
        "Switch log files."
        self._filename = filename

    def load(self):
        "Load the bisection log."
        self._items = []
        if os.path.exists(self._filename):
            revlog = self._open_for_read()
            for line in revlog:
                (revid, status) = line.split()
                self._items.append((revid, status))

    def save(self):
        "Save the bisection log."
        revlog = self._open_for_write()
        for (revid, status) in self._items:
            revlog.write("%s %s\n" % (revid, status))

    def is_done(self):
        "Report whether we've found the right revision."
        return len(self._items) > 0 and self._items[-1][1] == "done"

    def set_status_from_revspec(self, revspec, status):
        "Set the bisection status for the revision in revspec."
        self._load_bzr_tree()
        revid = revspec[0].in_history(self._bzrbranch).rev_id
        self._set_status(revid, status)

    def set_current(self, status):
        "Set the current revision to the given bisection status."
        self._set_status(self._current.get_current_revid(), status)

    def bisect(self):
        "Using the current revision's status, do a bisection."
        self._find_range_and_middle()
        self._switch_wc_to_revno(self._middle_revid)

        # If we've found the "final" revision, check for a
        # merge point.

        if self._middle_revid == self._high_revid or \
           self._middle_revid == self._low_revid:
            if self._current.is_merge_point():
                for parent in self._current.get_parent_revids():
                    if parent == self._low_revid:
                        continue
                    else:
                        self._find_range_and_middle(parent)
                        self._switch_wc_to_revno(self._middle_revid)
                        break
            else:
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

    bzr bisect start
        Start a bisect, possibly clearing out a previous bisect.

    bzr bisect yes [-r rev]
        The specified revision (or the current revision, if not given)
        has the characteristic we're looking for,

    bzr bisect no [-r rev]
        The specified revision (or the current revision, if not given)
        does not have the characteristic we're looking for,

    bzr bisect move -r rev
        Switch to a different revision manually.  Use if the bisect
        algorithm chooses a revision that is not suitable.  Try to
        move as little as possible.

    bzr bisect reset
        Clear out a bisection in progress.

    bzr bisect log [-o file]
        Output a log of the current bisection to standard output, or
        to the specified file.

    bzr bisect replay <logfile>
        Replay a previously-saved bisect log, forgetting any bisection
        that might be in progress.
    """

    takes_args = ['subcommand', 'args*']
    takes_options = [Option('output', short_name='o',
                            help='Write log to this file.', type=unicode),
                     'revision']

    def _check(self):
        "Check preconditions for most operations to work."
        if not os.path.exists(bisect_info_path):
            raise BzrCommandError("No bisect info found")

    def _set_state(self, revspec, state):
        "Set the state of the given revspec and bisecting."
        bisect_log = BisectLog()
        if bisect_log.is_done():
            sys.stdout.write("No further bisection is possible.\n")
            bisect_log._current.show_rev_log(sys.stdout)
            return

        if revspec:
            bisect_log.set_status_from_revspec(revspec, state)
        else:
            bisect_log.set_current(state)
        bisect_log.bisect()
        bisect_log.save()

    def run(self, subcommand, args_list, revision=None, output=None):
        "Handle the bisect command."

        log_fn = None
        if subcommand in ('yes', 'no', 'move') and revision:
            pass
        elif subcommand in ('replay', ) and args_list and len(args_list) == 1:
            log_fn = args_list[0]
        elif subcommand in ('move', ) and not revision:
            raise BzrCommandError(
                "The 'bisect move' command requires a revision.")
        elif args_list or revision:
            raise BzrCommandError(
                "Improper arguments to bisect " + subcommand)

        # Dispatch.

        if subcommand == "start":
            self.start()
        elif subcommand == "yes":
            self.yes(revision)
        elif subcommand == "no":
            self.no(revision)
        elif subcommand == "move":
            self.move(revision)
        elif subcommand == "reset":
            self.reset()
        elif subcommand == "log":
            self.log(output)
        elif subcommand == "replay":
            self.replay(log_fn)
        else:
            raise BzrCommandError(
                "Unknown bisect command: " + subcommand)

    def reset(self):
        "Reset the bisect state to no state."

        if os.path.exists(bisect_info_path):
            BisectCurrent().reset()
            os.unlink(bisect_info_path)
        else:
            sys.stdout.write("No bisection in progress; nothing to do.\n")

    def start(self):
        "Reset the bisect state, then prepare for a new bisection."

        if os.path.exists(bisect_info_path):
            BisectCurrent().reset()
            os.unlink(bisect_info_path)

        bisect_log = BisectLog()
        bisect_log.set_current("start")
        bisect_log.save()

    def yes(self, revspec):
        "Mark that a given revision has the state we're looking for."

        self._set_state(revspec, "yes")

    def no(self, revspec):
        "Mark that a given revision does not have the state we're looking for."

        self._set_state(revspec, "no")

    def move(self, revspec):
        "Move to a different revision manually."

        current = BisectCurrent()
        current.switch(revspec)
        current.show_rev_log()

    def log(self, filename):
        "Write the current bisect log to a file."

        self._check()

        bisect_log = BisectLog()
        bisect_log.change_file_name(filename)
        bisect_log.save()

    def replay(self, filename):
        """Apply the given log file to a clean state, so the state is
        exactly as it was when the log was saved."""

        self.reset()

        bisect_log = BisectLog(filename)
        bisect_log.change_file_name(bisect_info_path)
        bisect_log.save()

        bisect_log.bisect()

register_command(cmd_bisect)


def test_suite():
    "Set up the test suite for the plugin."
    from bzrlib.plugins.bisect import tests
    return tests.test_suite()
