# Copyright (C) 2006, 2007 Canonical Ltd
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

"""The basic test suite for bzr-git."""

import subprocess
import time

from bzrlib import (
    tests,
    trace,
    )

TestCase = tests.TestCase
TestCaseInTempDir = tests.TestCaseInTempDir
TestCaseWithTransport = tests.TestCaseWithTransport


class _GitCommandFeature(tests.Feature):

    def _probe(self):
        try:
            p = subprocess.Popen(['git', '--version'], stdout=subprocess.PIPE)
        except IOError:
            return False
        out, err = p.communicate()
        trace.mutter('Using: %s', out.rstrip('\n'))
        return True

    def feature_name(self):
        return 'git'

GitCommandFeature = _GitCommandFeature()


def run_git(*args):
    cmd = ['git'] + list(args)
    p = subprocess.Popen(cmd,
                         stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE)
    out, err = p.communicate()
    if p.returncode != 0:
        raise AssertionError('Bad return code: %d for %s:\n%s'
                             % (p.returncode, ' '.join(cmd), err))
    return out


class GitBranchBuilder(object):

    def __init__(self, stream):
        self.commit_info = []
        self.stream = stream
        self._counter = 0
        self._branch = 'refs/head/master'

    def set_branch(self, branch):
        """Set the branch we are committing."""
        self._branch = branch

    def _create_blob(self, content):
        self._counter += 1
        self.stream.write('blob\n')
        self.stream.write('mark :%d\n' % (self._counter,))
        self.stream.write('data %d\n' % (len(content),))
        self.stream.write(content)
        self.stream.write('\n')
        return self._counter

    def set_file(self, path, content, executable):
        """Create or update content at a given path."""
        mark = self._create_blob(content)
        if executable:
            mode = '100755'
        else:
            mode = '100644'
        self.commit_info.append('M %s :%d %s\n'
                                % (mode, mark, path.encode('utf-8')))

    def set_link(self, path, link_target):
        """Create or update a link at a given path."""
        mark = self._create_blob(link_target)
        self.commit_info.append('M 120000 :%d %s\n'
                                % (mark, path.encode('utf-8')))

    def delete_entry(self, path):
        """This will delete files or symlinks at the given location."""
        self.commit_info.append('D %s\n' % (path.encode('utf-8'),))

    def commit(self, committer, message, timestamp=None,
               timezone='+0000', author=None):
        self._counter += 1
        mark = self._counter
        self.stream.write('commit %s\n' % (branch,))
        self.stream.write('mark :%d\n' % (mark,))
        self.stream.write('committer %s %s %s\n'
                          % (committer, timestamp, timezone))
        message = message.encode('UTF-8')
        self.stream.write('data %d\n' % (len(message),))
        self.stream.write(message)
        self.stream.write('\n')
        self.stream.writelines(self.commit_info)
        self.stream.write('\n')
        self.commit_info = []
        return mark


class GitBranchBuilder(object):
    """This uses git-fast-import to build up something directly."""

    def __init__(self, git_dir):
        self.git_dir = git_dir


def test_suite():
    loader = tests.TestLoader()

    suite = tests.TestSuite()

    testmod_names = [
        'test_builder',
        'test_git_branch',
        'test_git_dir',
        'test_git_repository',
        'test_model',
        'test_ids',
        ]
    testmod_names = ['%s.%s' % (__name__, t) for t in testmod_names]
    suite.addTests(loader.loadTestsFromModuleNames(testmod_names))

    return suite
