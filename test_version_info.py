# Copyright (C) 2005 Canonical Ltd

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

"""\
Tests for version_info
"""

import os
import sys

from StringIO import StringIO
from bzrlib.tests import TestCase, TestCaseInTempDir
from bzrlib.branch import Branch
from bzrlib.rio import read_stanzas

# TODO: jam 20051228 When part of bzrlib, this should become
#       from bzrlib.generate_version_info import foo

from generate_version_info import (is_clean,
        generate_rio_version, generate_python_version)


class TestIsClean(TestCaseInTempDir):

    # TODO: jam 20051228 Test that a branch without a working tree
    #       is clean. This would be something like an SFTP test

    def test_is_clean(self):
        b = Branch.initialize('.')
        wt = b.working_tree()

        def not_clean(b):
            clean, message = is_clean(b)
            if clean:
                self.fail('Tree should not be clean')

        def check_clean(b):
            clean, message = is_clean(b)
            if not clean:
                self.fail(message)

        # Nothing happened yet
        check_clean(b)

        # Unknown file
        open('a', 'wb').write('a file\n')
        not_clean(b)
        
        # Newly added file
        wt.add('a')
        not_clean(b)

        # We committed, things are clean
        wt.commit('added a')
        check_clean(b)

        # Unknown
        open('b', 'wb').write('b file\n')
        not_clean(b)

        wt.add('b')
        not_clean(b)

        wt.commit('added b')
        check_clean(b)

        open('a', 'wb').write('different\n')
        not_clean(b)

        wt.commit('mod a')
        check_clean(b)

        os.remove('a')
        not_clean(b)

        wt.commit('del a')
        check_clean(b)

        wt.rename_one('b', 'a')
        not_clean(b)

        wt.commit('rename b => a')
        check_clean(b)


class TestVersionInfo(TestCaseInTempDir):

    def create_branch(self):
        os.mkdir('branch')
        b = Branch.initialize(u'branch')
        wt = b.working_tree()
        
        open('branch/a', 'wb').write('a file\n')
        wt.add('a')
        wt.commit('a', rev_id='r1')

        open('branch/b', 'wb').write('b file\n')
        wt.add('b')
        wt.commit('b', rev_id='r2')

        open('branch/a', 'wb').write('new contents\n')
        wt.commit('a2', rev_id='r3')

        return b, wt

    def test_rio_version_text(self):
        b, wt = self.create_branch()

        def regen(**kwargs):
            sio = StringIO()
            generate_rio_version(b, to_file=sio, **kwargs)
            val = sio.getvalue()
            return val

        val = regen()
        self.assertContainsRe(val, 'date:')
        self.assertContainsRe(val, 'revno: 3')
        self.assertContainsRe(val, 'revision_id: r3')

        val = regen(check_for_clean=True)
        self.assertContainsRe(val, 'clean: True')

        open('branch/c', 'wb').write('now unclean\n')
        val = regen(check_for_clean=True)
        self.assertContainsRe(val, 'clean: False')
        os.remove('branch/c')

        val = regen(include_revision_history=True)
        self.assertContainsRe(val, 'id: r1')
        self.assertContainsRe(val, 'message: a')
        self.assertContainsRe(val, 'id: r2')
        self.assertContainsRe(val, 'message: b')
        self.assertContainsRe(val, 'id: r3')
        self.assertContainsRe(val, 'message: a2')

    def test_rio_version(self):
        b, wt = self.create_branch()

        def regen(**kwargs):
            sio = StringIO()
            generate_rio_version(b, to_file=sio, **kwargs)
            sio.seek(0)
            stanzas = list(read_stanzas(sio))
            self.assertEqual(1, len(stanzas))
            return stanzas[0]

        stanza = regen()
        self.failUnless('date' in stanza)
        self.assertEqual(['3'], stanza.get_all('revno'))
        self.assertEqual(['r3'], stanza.get_all('revision_id'))

        stanza = regen(check_for_clean=True)
        self.assertEqual(['True'], stanza.get_all('clean'))

        open('branch/c', 'wb').write('now unclean\n')
        stanza = regen(check_for_clean=True)
        self.assertEqual(['False'], stanza.get_all('clean'))
        os.remove('branch/c')

        stanza = regen(include_revision_history=True)
        txt = stanza['revisions']
        revision_stanza = list(read_stanzas(StringIO(txt)))
        self.assertEqual(1, len(revision_stanza))
        revision_stanza = revision_stanza[0]
        self.assertEqual(['r1', 'r2', 'r3'], revision_stanza.get_all('id'))
        self.assertEqual(['a', 'b', 'a2'], revision_stanza.get_all('message'))

    def test_python_version(self):
        b, wt = self.create_branch()

        def regen(**kwargs):
            outf = open('test_version_information.py', 'wb')
            generate_python_version(b, to_file=outf, **kwargs)
            outf.close()
            try:
                sys.path.append(os.getcwdu())
                import test_version_information as tvi
                reload(tvi)
            finally:
                sys.path.pop()
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
        self.assertEquals(3, tvi.version_info['revno'])
        self.assertEquals('r3', tvi.version_info['revision_id'])
        self.failUnless(tvi.version_info.has_key('date'))
        self.assertEquals(None, tvi.version_info['clean'])

        tvi = regen(check_for_clean=True)
        self.assertEquals(True, tvi.version_info['clean'])

        open('branch/c', 'wb').write('now unclean\n')
        tvi = regen(check_for_clean=True)
        self.assertEquals(False, tvi.version_info['clean'])
        os.remove('branch/c')

        tvi = regen(include_revision_history=True)
        self.assertEqual([('r1', 'a'), ('r2', 'b'), ('r3', 'a2')],
                         tvi.version_info['revisions'])


