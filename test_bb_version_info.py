# Copyright (C) 2005, 2006 Canonical Ltd
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

"""Blackbox tests for version_info"""

import imp
import os
import sys

from bzrlib.tests import TestCase, TestCaseWithTransport


class TestVersionInfo(TestCaseWithTransport):

    def test_invalid_format(self):
        bzr = self.run_bzr

        bzr('version-info', '--format', 'quijibo', retcode=3)

    def create_branch(self):
        wt = self.make_branch_and_tree('branch')
        
        self.build_tree(['branch/a'])
        wt.add('a')
        wt.commit('adding a', rev_id='r1')

        self.build_tree(['branch/b'])
        wt.add('b')
        wt.commit('adding b', rev_id='r2')

        self.revisions = wt.branch.revision_history()

    def test_rio(self):
        self.create_branch()

        def regen(*args):
            return self.run_bzr('version-info', '--format', 'rio', 
                                'branch', *args)[0]

        txt = regen()
        self.assertContainsRe(txt, 'date:')
        self.assertContainsRe(txt, 'build-date:')
        self.assertContainsRe(txt, 'revno: 2')
        self.assertContainsRe(txt, 'revision-id: ' + self.revisions[-1])

        txt = regen('--all')
        self.assertContainsRe(txt, 'date:')
        self.assertContainsRe(txt, 'revno: 2')
        self.assertContainsRe(txt, 'revision-id: ' + self.revisions[-1])
        self.assertContainsRe(txt, 'clean: True')
        self.assertContainsRe(txt, 'revisions:')
        for rev_id in self.revisions:
            self.assertContainsRe(txt, 'id: ' + rev_id)
        self.assertContainsRe(txt, 'message: adding a')
        self.assertContainsRe(txt, 'message: adding b')
        self.assertContainsRe(txt, 'file-revisions:')
        self.assertContainsRe(txt, 'path: a')
        self.assertContainsRe(txt, 'path: b')

        txt = regen('--check-clean')
        self.assertContainsRe(txt, 'clean: True')

        open('branch/c', 'wb').write('now unclean\n')
        txt = regen('--check-clean')
        self.assertContainsRe(txt, 'clean: False')

        txt = regen('--check-clean', '--include-file-revisions')
        self.assertContainsRe(txt, 'revision: unversioned')

        os.remove('branch/c')

        # Make sure it works without a directory
        os.chdir('branch')
        txt = self.run_bzr('version-info', '--format', 'rio')

    def test_python(self):
        def bzr(*args, **kwargs):
            return self.run_bzr(*args, **kwargs)[0]

        def regen(*args):
            txt = self.run_bzr('version-info', '--format', 'python',
                               'branch', *args)[0]
            outf = open('test_version_information.py', 'wb')
            outf.write(txt)
            outf.close()
            module_info = imp.find_module('test_version_information',
                                          [os.getcwdu()])
            tvi = imp.load_module('tvi', *module_info)
            # Make sure the module isn't cached
            sys.modules.pop('tvi', None)
            sys.modules.pop('test_version_information', None)
            # Delete the compiled versions, because we are generating
            # a new file fast enough that python doesn't detect it
            # needs to recompile, and using sleep() just makes the
            # test slow
            if os.path.exists('test_version_information.pyc'):
                os.remove('test_version_information.pyc')
            if os.path.exists('test_version_information.pyo'):
                os.remove('test_version_information.pyo')
            return tvi

        self.create_branch()

        tvi = regen()
        self.assertEqual(tvi.version_info['revno'], 2)
        self.failUnless(tvi.version_info.has_key('date'))
        self.assertEqual(self.revisions[-1], tvi.version_info['revision_id'])
        self.assertEqual({}, tvi.revisions)
        self.assertEqual({}, tvi.file_revisions)

        tvi = regen('--all')
        rev_info = [(rev, message) for rev, message, timestamp, timezone 
                                   in tvi.revisions] 
        self.assertEqual([(self.revisions[0], 'adding a'),
                          (self.revisions[1], 'adding b')],
                         rev_info)
        self.assertEqual(True, tvi.version_info['clean'])
        file_revisions = []
        for path in sorted(tvi.file_revisions.keys()):
            file_revisions.append((path, tvi.file_revisions[path]))
        self.assertEqual([('a', self.revisions[0]), ('b', self.revisions[1])],
            file_revisions)

        open('branch/c', 'wb').write('now unclean\n')
        tvi = regen('--check-clean', '--include-file-revisions')
        self.assertEqual(False, tvi.version_info['clean'])
        self.assertEqual('unversioned', tvi.file_revisions['c'])
        os.remove('branch/c')


