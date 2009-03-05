# Copyright (C) 2005, 2006, 2009 Canonical Ltd
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


"""Black-box tests for default log_formats/log_formatters
"""


import os


from bzrlib.branch import Branch
from bzrlib.tests import TestCaseInTempDir
from bzrlib.config import (ensure_config_dir_exists, config_filename)


class TestLogFormats(TestCaseInTempDir):

    def test_log_default_format(self):
        self.setup_config()

        self.run_bzr('init')
        open('a', 'wb').write('foo\n')
        self.run_bzr('add a')

        self.run_bzr('commit -m 1')
        open('a', 'wb').write('baz\n')

        self.run_bzr('commit -m 2')

        # only the lines formatter is this short
        self.assertEquals(3, len(self.run_bzr('log')[0].split('\n')))

    def test_log_format_arg(self):
        self.run_bzr('init')
        open('a', 'wb').write('foo\n')
        self.run_bzr('add a')

        self.run_bzr('commit -m 1')
        open('a', 'wb').write('baz\n')

        self.run_bzr('commit -m 2')

        # only the lines formatter is this short
        self.assertEquals(7,
            len(self.run_bzr('log --log-format short')[0].split('\n')))

    def test_missing_default_format(self):
        self.setup_config()

        os.mkdir('a')
        os.chdir('a')
        self.run_bzr('init')

        open('a', 'wb').write('foo\n')
        self.run_bzr('add a')
        self.run_bzr('commit -m 1')

        os.chdir('..')
        self.run_bzr('branch a b')
        os.chdir('a')

        open('a', 'wb').write('bar\n')
        self.run_bzr('commit -m 2')

        open('a', 'wb').write('baz\n')
        self.run_bzr('commit -m 3')

        os.chdir('../b')

        self.assertEquals(5,
            len(self.run_bzr('missing', retcode=1)[0].split('\n')))

        os.chdir('..')

    def test_missing_format_arg(self):
        self.setup_config()

        os.mkdir('a')
        os.chdir('a')
        self.run_bzr('init')

        open('a', 'wb').write('foo\n')
        self.run_bzr('add a')
        self.run_bzr('commit -m 1')

        os.chdir('..')
        self.run_bzr('branch a b')
        os.chdir('a')

        open('a', 'wb').write('bar\n')
        self.run_bzr('commit -m 2')

        open('a', 'wb').write('baz\n')
        self.run_bzr('commit -m 3')

        os.chdir('../b')

        self.assertEquals(9,
            len(self.run_bzr('missing --log-format short',
                retcode=1)[0].split('\n')))

        os.chdir('..')

    def test_logformat_gnu_changelog(self):
        # from http://launchpad.net/bugs/29582/
        self.setup_config()
        repo_url = self.make_trivial_history()

        out, err = self.run_bzr(
            ['log', self.get_url('repo/a'),
             '--log-format=gnu-changelog',
             '--timezone=utc'])
        self.assertEquals(err, '')
        self.assertEqualDiff(out,
"""2009-03-03  Joe Foo  <joe@foo.com>

\tcommit 1

""")

    def make_trivial_history(self):
        """Make a one-commit history and return the URL of the branch"""
        repo = self.make_repository('repo', shared=True, format='1.6')
        bb = self.make_branch_builder('repo/a')
        bb.start_series()
        bb.build_snapshot('rev-1', None,
            [('add', ('', 'root-id', 'directory', ''))],
            timestamp=1236045060)
        bb.finish_series()
        return self.get_url('repo/a')

    def setup_config(self):
        if os.path.isfile(config_filename()):
                # Something is wrong in environment,
                # we risk overwriting users config
                self.assert_(config_filename() + "exists, abort")

        ensure_config_dir_exists()
        CONFIG=("[DEFAULT]\n"
                "email=Joe Foo <joe@foo.com>\n"
                "log_format=line\n")

        open(config_filename(),'wb').write(CONFIG)
