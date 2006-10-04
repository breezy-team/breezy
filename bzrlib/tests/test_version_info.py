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

"""Tests for version_info"""

from cStringIO import StringIO
import imp
import os
import sys

from bzrlib.tests import TestCaseWithTransport
from bzrlib.rio import read_stanzas

from bzrlib.version_info_formats.format_rio import RioVersionInfoBuilder
from bzrlib.version_info_formats.format_python import PythonVersionInfoBuilder


class TestVersionInfo(TestCaseWithTransport):

    def create_branch(self):
        wt = self.make_branch_and_tree('branch')

        self.build_tree(['branch/a'])
        wt.add('a')
        wt.commit('a', rev_id='r1')

        self.build_tree(['branch/b'])
        wt.add('b')
        wt.commit('b', rev_id='r2')

        self.build_tree_contents([('branch/a', 'new contents\n')])
        wt.commit(u'\xe52', rev_id='r3')

        return wt

    def test_rio_version_text(self):
        wt = self.create_branch()

        def regen(**kwargs):
            sio = StringIO()
            builder = RioVersionInfoBuilder(wt.branch, working_tree=wt,
                                            **kwargs)
            builder.generate(sio)
            val = sio.getvalue()
            return val

        val = regen()
        self.assertContainsRe(val, 'build-date:')
        self.assertContainsRe(val, 'date:')
        self.assertContainsRe(val, 'revno: 3')
        self.assertContainsRe(val, 'revision-id: r3')

        val = regen(check_for_clean=True)
        self.assertContainsRe(val, 'clean: True')

        self.build_tree(['branch/c'])
        val = regen(check_for_clean=True)
        self.assertContainsRe(val, 'clean: False')
        os.remove('branch/c')

        val = regen(include_revision_history=True)
        self.assertContainsRe(val, 'id: r1')
        self.assertContainsRe(val, 'message: a')
        self.assertContainsRe(val, 'id: r2')
        self.assertContainsRe(val, 'message: b')
        self.assertContainsRe(val, 'id: r3')
        self.assertContainsRe(val, 'message: \xc3\xa52') # utf8 encoding '\xe5'

    def test_rio_version(self):
        wt = self.create_branch()

        def regen(**kwargs):
            sio = StringIO()
            builder = RioVersionInfoBuilder(wt.branch, working_tree=wt,
                                            **kwargs)
            builder.generate(sio)
            sio.seek(0)
            stanzas = list(read_stanzas(sio))
            self.assertEqual(1, len(stanzas))
            return stanzas[0]

        def get_one_stanza(stanza, key):
            new_stanzas = list(read_stanzas(
                                StringIO(stanza[key].encode('utf8'))))
            self.assertEqual(1, len(new_stanzas))
            return new_stanzas[0]

        stanza = regen()
        self.failUnless('date' in stanza)
        self.failUnless('build-date' in stanza)
        self.assertEqual(['3'], stanza.get_all('revno'))
        self.assertEqual(['r3'], stanza.get_all('revision-id'))

        stanza = regen(check_for_clean=True)
        self.assertEqual(['True'], stanza.get_all('clean'))

        self.build_tree(['branch/c'])
        stanza = regen(check_for_clean=True, include_file_revisions=True)
        self.assertEqual(['False'], stanza.get_all('clean'))

        file_rev_stanza = get_one_stanza(stanza, 'file-revisions')
        self.assertEqual(['a', 'b', 'c'], file_rev_stanza.get_all('path'))
        self.assertEqual(['r3', 'r2', 'unversioned'],
            file_rev_stanza.get_all('revision'))
        os.remove('branch/c')

        stanza = regen(include_revision_history=True)
        revision_stanza = get_one_stanza(stanza, 'revisions')
        self.assertEqual(['r1', 'r2', 'r3'], revision_stanza.get_all('id'))
        self.assertEqual(['a', 'b', u'\xe52'], revision_stanza.get_all('message'))
        self.assertEqual(3, len(revision_stanza.get_all('date')))

        # a was modified, so it should show up modified again
        self.build_tree(['branch/a', 'branch/c'])
        wt.add('c')
        wt.rename_one('b', 'd')
        stanza = regen(check_for_clean=True, include_file_revisions=True)
        file_rev_stanza = get_one_stanza(stanza, 'file-revisions')
        self.assertEqual(['a', 'b', 'c', 'd'], file_rev_stanza.get_all('path'))
        self.assertEqual(['modified', 'renamed to d', 'new', 'renamed from b'],
                         file_rev_stanza.get_all('revision'))

        wt.commit('modified', rev_id='r4')
        wt.remove(['c', 'd'])
        os.remove('branch/d')
        stanza = regen(check_for_clean=True, include_file_revisions=True)
        file_rev_stanza = get_one_stanza(stanza, 'file-revisions')
        self.assertEqual(['a', 'c', 'd'], file_rev_stanza.get_all('path'))
        self.assertEqual(['r4', 'unversioned', 'removed'],
                         file_rev_stanza.get_all('revision'))

    def test_python_version(self):
        wt = self.create_branch()

        def regen(**kwargs):
            """Create a test module, import and return it"""
            outf = open('test_version_information.py', 'wb')
            try:
                builder = PythonVersionInfoBuilder(wt.branch, working_tree=wt,
                                                   **kwargs)
                builder.generate(outf)
            finally:
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

        tvi = regen()
        self.assertEqual(3, tvi.version_info['revno'])
        self.assertEqual('r3', tvi.version_info['revision_id'])
        self.failUnless(tvi.version_info.has_key('date'))
        self.assertEqual(None, tvi.version_info['clean'])

        tvi = regen(check_for_clean=True)
        self.assertEqual(True, tvi.version_info['clean'])

        self.build_tree(['branch/c'])
        tvi = regen(check_for_clean=True, include_file_revisions=True)
        self.assertEqual(False, tvi.version_info['clean'])
        self.assertEqual(['a', 'b', 'c'], sorted(tvi.file_revisions.keys()))
        self.assertEqual('r3', tvi.file_revisions['a'])
        self.assertEqual('r2', tvi.file_revisions['b'])
        self.assertEqual('unversioned', tvi.file_revisions['c'])
        os.remove('branch/c')

        tvi = regen(include_revision_history=True)

        rev_info = [(rev, message) for rev, message, timestamp, timezone
                                   in tvi.revisions]
        self.assertEqual([('r1', 'a'), ('r2', 'b'), ('r3', u'\xe52')], rev_info)

        # a was modified, so it should show up modified again
        self.build_tree(['branch/a', 'branch/c'])
        wt.add('c')
        wt.rename_one('b', 'd')
        tvi = regen(check_for_clean=True, include_file_revisions=True)
        self.assertEqual(['a', 'b', 'c', 'd'], sorted(tvi.file_revisions.keys()))
        self.assertEqual('modified', tvi.file_revisions['a'])
        self.assertEqual('renamed to d', tvi.file_revisions['b'])
        self.assertEqual('new', tvi.file_revisions['c'])
        self.assertEqual('renamed from b', tvi.file_revisions['d'])

        wt.commit('modified', rev_id='r4')
        wt.remove(['c', 'd'])
        os.remove('branch/d')
        tvi = regen(check_for_clean=True, include_file_revisions=True)
        self.assertEqual(['a', 'c', 'd'], sorted(tvi.file_revisions.keys()))
        self.assertEqual('r4', tvi.file_revisions['a'])
        self.assertEqual('unversioned', tvi.file_revisions['c'])
        self.assertEqual('removed', tvi.file_revisions['d'])


