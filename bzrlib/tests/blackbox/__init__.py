# Copyright (C) 2005, 2006 by Canonical Ltd
# -*- coding: utf-8 -*-

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA


"""Black-box tests for bzr.

These check that it behaves properly when it's invoked through the regular
command-line interface. This doesn't actually run a new interpreter but 
rather starts again from the run_bzr function.
"""

from bzrlib.tests import (
                          _load_module_by_name,
                          TestCaseWithTransport,
                          TestSuite,
                          TestLoader,
                          )
import bzrlib.ui as ui


def test_suite():
    testmod_names = [
                     'bzrlib.tests.blackbox.test_added',
                     'bzrlib.tests.blackbox.test_aliases',
                     'bzrlib.tests.blackbox.test_ancestry',
                     'bzrlib.tests.blackbox.test_break_lock',
                     'bzrlib.tests.blackbox.test_bound_branches',
                     'bzrlib.tests.blackbox.test_cat',
                     'bzrlib.tests.blackbox.test_checkout',
                     'bzrlib.tests.blackbox.test_commit',
                     'bzrlib.tests.blackbox.test_conflicts',
                     'bzrlib.tests.blackbox.test_diff',
                     'bzrlib.tests.blackbox.test_export',
                     'bzrlib.tests.blackbox.test_find_merge_base',
                     'bzrlib.tests.blackbox.test_help',
                     'bzrlib.tests.blackbox.test_info',
                     'bzrlib.tests.blackbox.test_init',
                     'bzrlib.tests.blackbox.test_log',
                     'bzrlib.tests.blackbox.test_logformats',
                     'bzrlib.tests.blackbox.test_merge',
                     'bzrlib.tests.blackbox.test_missing',
                     'bzrlib.tests.blackbox.test_outside_wt',
                     'bzrlib.tests.blackbox.test_pull',
                     'bzrlib.tests.blackbox.test_push',
                     'bzrlib.tests.blackbox.test_reconcile',
                     'bzrlib.tests.blackbox.test_re_sign',
                     'bzrlib.tests.blackbox.test_revert',
                     'bzrlib.tests.blackbox.test_revno',
                     'bzrlib.tests.blackbox.test_revision_info',
                     'bzrlib.tests.blackbox.test_selftest',
                     'bzrlib.tests.blackbox.test_sign_my_commits',
                     'bzrlib.tests.blackbox.test_status',
                     'bzrlib.tests.blackbox.test_too_much',
                     'bzrlib.tests.blackbox.test_update',
                     'bzrlib.tests.blackbox.test_upgrade',
                     'bzrlib.tests.blackbox.test_versioning',
                     ]

    suite = TestSuite()
    loader = TestLoader()
    for mod_name in testmod_names:
        mod = _load_module_by_name(mod_name)
        suite.addTest(loader.loadTestsFromModule(mod))
    return suite


class ExternalBase(TestCaseWithTransport):

    def runbzr(self, args, retcode=0, backtick=False):
        if isinstance(args, basestring):
            args = args.split()
        if backtick:
            return self.run_bzr_captured(args, retcode=retcode)[0]
        else:
            return self.run_bzr_captured(args, retcode=retcode)


class TestUIFactory(ui.UIFactory):
    """A UI Factory for testing - hide the progress bar but emit note()s."""

    def clear(self):
        """See progress.ProgressBar.clear()."""

    def finished(self):
        """See progress.ProgressBar.finished()."""

    def note(self, fmt_string, *args, **kwargs):
        """See progress.ProgressBar.note()."""
        print fmt_string % args

    def progress_bar(self):
        return self
    
    def nested_progress_bar(self):
        return self

    def update(self, message, count=None, total=None):
        """See progress.ProgressBar.update()."""
