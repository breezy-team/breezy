# Copyright (C) 2005 Canonical Ltd
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

"""Test commit message editor.
"""

import os
import sys

import bzrlib
from bzrlib import (
    errors,
    msgeditor,
    osutils,
    tests,
    )
from bzrlib.branch import Branch
from bzrlib.config import ensure_config_dir_exists, config_filename
from bzrlib.msgeditor import (
    make_commit_message_template_encoded,
    edit_commit_message_encoded
)
from bzrlib.tests import (
    iter_suite_tests,
    probe_bad_non_ascii,
    split_suite_by_re,
    TestCaseWithTransport,
    TestNotApplicable,
    TestSkipped,
    )
from bzrlib.tests.EncodingAdapter import EncodingTestAdapter
from bzrlib.trace import mutter


def load_tests(standard_tests, module, loader):
    """Parameterize the test for tempfile creation with different encodings."""
    to_adapt, result = split_suite_by_re(standard_tests,
        "test__create_temp_file_with_commit_template_in_unicode_dir")
    for test in iter_suite_tests(to_adapt):
        result.addTests(EncodingTestAdapter().adapt(test))
    return result


class MsgEditorTest(TestCaseWithTransport):

    def make_uncommitted_tree(self):
        """Build a branch with uncommitted unicode named changes in the cwd."""
        working_tree = self.make_branch_and_tree('.')
        b = working_tree.branch
        filename = u'hell\u00d8'
        try:
            self.build_tree_contents([(filename, 'contents of hello')])
        except UnicodeEncodeError:
            raise TestSkipped("can't build unicode working tree in "
                "filesystem encoding %s" % sys.getfilesystemencoding())
        working_tree.add(filename)
        return working_tree
    
    def test_commit_template(self):
        """Test building a commit message template"""
        working_tree = self.make_uncommitted_tree()
        template = msgeditor.make_commit_message_template(working_tree,
                                                                 None)
        self.assertEqualDiff(template,
u"""\
added:
  hell\u00d8
""")

    def test_commit_template_encoded(self):
        """Test building a commit message template"""
        working_tree = self.make_uncommitted_tree()
        template = make_commit_message_template_encoded(working_tree,
                                                        None,
                                                        output_encoding='utf8')
        self.assertEqualDiff(template,
u"""\
added:
  hell\u00d8
""".encode("utf8"))


    def test_commit_template_and_diff(self):
        """Test building a commit message template"""
        working_tree = self.make_uncommitted_tree()
        template = make_commit_message_template_encoded(working_tree,
                                                        None,
                                                        diff=True,
                                                        output_encoding='utf8')

        self.assertTrue("""\
@@ -0,0 +1,1 @@
+contents of hello
""" in template)
        self.assertTrue(u"""\
added:
  hell\u00d8
""".encode('utf8') in template)

    def test_run_editor(self):
        if sys.platform == "win32":
            f = file('fed.bat', 'w')
            f.write('@rem dummy fed')
            f.close()
            os.environ['BZR_EDITOR'] = 'fed.bat'
        else:
            f = file('fed.sh', 'wb')
            f.write('#!/bin/sh\n')
            f.close()
            os.chmod('fed.sh', 0755)
            os.environ['BZR_EDITOR'] = './fed.sh'

        self.assertEqual(True, msgeditor._run_editor(''),
                         'Unable to run dummy fake editor')

    def make_fake_editor(self, message='test message from fed\\n'):
        """Set up environment so that an editor will be a known script.

        Sets up BZR_EDITOR so that if an editor is spawned it will run a
        script that just adds a known message to the start of the file.
        """
        f = file('fed.py', 'wb')
        f.write('#!%s\n' % sys.executable)
        f.write("""\
# coding=utf-8
import sys
if len(sys.argv) == 2:
    fn = sys.argv[1]
    f = file(fn, 'rb')
    s = f.read()
    f.close()
    f = file(fn, 'wb')
    f.write('%s')
    f.write(s)
    f.close()
""" % (message, ))
        f.close()
        if sys.platform == "win32":
            # [win32] make batch file and set BZR_EDITOR
            f = file('fed.bat', 'w')
            f.write("""\
@echo off
"%s" fed.py %%1
""" % sys.executable)
            f.close()
            os.environ['BZR_EDITOR'] = 'fed.bat'
        else:
            # [non-win32] make python script executable and set BZR_EDITOR
            os.chmod('fed.py', 0755)
            os.environ['BZR_EDITOR'] = './fed.py'

    def test_edit_commit_message(self):
        working_tree = self.make_uncommitted_tree()
        self.make_fake_editor()

        mutter('edit_commit_message without infotext')
        self.assertEqual('test message from fed\n',
                         msgeditor.edit_commit_message(''))

        mutter('edit_commit_message with ascii string infotext')
        self.assertEqual('test message from fed\n',
                         msgeditor.edit_commit_message('spam'))

        mutter('edit_commit_message with unicode infotext')
        self.assertEqual('test message from fed\n',
                         msgeditor.edit_commit_message(u'\u1234'))

        tmpl = edit_commit_message_encoded(u'\u1234'.encode("utf8"))
        self.assertEqual('test message from fed\n', tmpl)

    def test_start_message(self):
        self.make_uncommitted_tree()
        self.make_fake_editor()
        self.assertEqual('test message from fed\nstart message\n',
                         msgeditor.edit_commit_message('',
                                              start_message='start message\n'))
        self.assertEqual('test message from fed\n',
                         msgeditor.edit_commit_message('',
                                              start_message=''))

    def test_deleted_commit_message(self):
        working_tree = self.make_uncommitted_tree()

        if sys.platform == 'win32':
            os.environ['BZR_EDITOR'] = 'cmd.exe /c del'
        else:
            os.environ['BZR_EDITOR'] = 'rm'

        self.assertRaises((IOError, OSError), msgeditor.edit_commit_message, '')

    def test__get_editor(self):
        # Test that _get_editor can return a decent list of items
        bzr_editor = os.environ.get('BZR_EDITOR')
        visual = os.environ.get('VISUAL')
        editor = os.environ.get('EDITOR')
        try:
            os.environ['BZR_EDITOR'] = 'bzr_editor'
            os.environ['VISUAL'] = 'visual'
            os.environ['EDITOR'] = 'editor'

            ensure_config_dir_exists()
            f = open(config_filename(), 'wb')
            f.write('editor = config_editor\n')
            f.close()

            editors = list(msgeditor._get_editor())

            self.assertEqual(['bzr_editor', 'config_editor', 'visual',
                              'editor'], editors[:4])

            if sys.platform == 'win32':
                self.assertEqual(['wordpad.exe', 'notepad.exe'], editors[4:])
            else:
                self.assertEqual(['/usr/bin/editor', 'vi', 'pico', 'nano',
                                  'joe'], editors[4:])

        finally:
            # Restore the environment
            if bzr_editor is None:
                del os.environ['BZR_EDITOR']
            else:
                os.environ['BZR_EDITOR'] = bzr_editor
            if visual is None:
                del os.environ['VISUAL']
            else:
                os.environ['VISUAL'] = visual
            if editor is None:
                del os.environ['EDITOR']
            else:
                os.environ['EDITOR'] = editor

    def test__create_temp_file_with_commit_template(self):
        # check that commit template written properly
        # and has platform native line-endings (CRLF on win32)
        create_file = msgeditor._create_temp_file_with_commit_template
        msgfilename, hasinfo = create_file('infotext','----','start message')
        self.assertNotEqual(None, msgfilename)
        self.assertTrue(hasinfo)
        expected = os.linesep.join(['start message',
                                    '',
                                    '',
                                    '----',
                                    '',
                                    'infotext'])
        self.assertFileEqual(expected, msgfilename)

    def test__create_temp_file_with_commit_template_in_unicode_dir(self):
        self.requireFeature(tests.UnicodeFilenameFeature)
        if hasattr(self, 'info'):
            os.mkdir(self.info['directory'])
            os.chdir(self.info['directory'])
            msgeditor._create_temp_file_with_commit_template('infotext')
        else:
            raise TestNotApplicable('Test run elsewhere with non-ascii data.')

    def test__create_temp_file_with_empty_commit_template(self):
        # empty file
        create_file = msgeditor._create_temp_file_with_commit_template
        msgfilename, hasinfo = create_file('')
        self.assertNotEqual(None, msgfilename)
        self.assertFalse(hasinfo)
        self.assertFileEqual('', msgfilename)

    def test_unsupported_encoding_commit_message(self):
        old_env = osutils.set_or_unset_env('LANG', 'C')
        try:
            # LANG env variable has no effect on Windows
            # but some characters anyway cannot be represented
            # in default user encoding
            char = probe_bad_non_ascii(bzrlib.user_encoding)
            if char is None:
                raise TestSkipped('Cannot find suitable non-ascii character '
                    'for user_encoding (%s)' % bzrlib.user_encoding)

            self.make_fake_editor(message=char)

            working_tree = self.make_uncommitted_tree()
            self.assertRaises(errors.BadCommitMessageEncoding,
                              msgeditor.edit_commit_message, '')
        finally:
            osutils.set_or_unset_env('LANG', old_env)
