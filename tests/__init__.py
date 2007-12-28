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
    osutils,
    tests,
    trace,
    )
from  bzrlib.plugins.git import errors

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

    def __init__(self, stream=None):
        self.commit_info = []
        self.stream = stream
        self._process = None
        self._counter = 0
        self._branch = 'refs/heads/master'
        if stream is None:
            # Write the marks file into the git sandbox.
            self._marks_file_name = osutils.abspath('marks')
            self._process = subprocess.Popen(
                ['git', 'fast-import', '--quiet',
                 # GIT doesn't support '--export-marks foo'
                 # it only supports '--export-marks=foo'
                 # And gives a 'unknown option' otherwise.
                 '--export-marks=' + self._marks_file_name,
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.PIPE,
                )
            self.stream = self._process.stdin
        else:
            self._process = None

    def set_branch(self, branch):
        """Set the branch we are committing."""
        self._branch = branch

    def _write(self, text):
        try:
            self.stream.write(text)
        except IOError, e:
            if self._process is None:
                raise
            raise errors.GitCommandError(self._process.returncode,
                                         'git fast-import',
                                         self._process.stderr.read())

    def _writelines(self, lines):
        try:
            self.stream.writelines(lines)
        except IOError, e:
            if self._process is None:
                raise
            raise errors.GitCommandError(self._process.returncode,
                                         'git fast-import',
                                         self._process.stderr.read())

    def _create_blob(self, content):
        self._counter += 1
        self._write('blob\n')
        self._write('mark :%d\n' % (self._counter,))
        self._write('data %d\n' % (len(content),))
        self._write(content)
        self._write('\n')
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

    # TODO: Author
    # TODO: Author timestamp+timezone
    def commit(self, committer, message, timestamp=None,
               timezone='+0000', author=None,
               merge=None, base=None):
        """Commit the new content.

        :param committer: The name and address for the committer
        :param message: The commit message
        :param timestamp: The timestamp for the commit
        :param timezone: The timezone of the commit, such as '+0000' or '-1000'
        :param author: The name and address of the author (if different from
            committer)
        :param merge: A list of marks if this should merge in another commit
        :param base: An id for the base revision (primary parent) if that
            is not the last commit.
        :return: A mark which can be used in the future to reference this
            commit.
        """
        self._counter += 1
        mark = self._counter
        if timestamp is None:
            timestamp = int(time.time())
        self._write('commit %s\n' % (self._branch,))
        self._write('mark :%d\n' % (mark,))
        self._write('committer %s %s %s\n'
                    % (committer, timestamp, timezone))
        message = message.encode('UTF-8')
        self._write('data %d\n' % (len(message),))
        self._write(message)
        self._write('\n')
        if base is not None:
            self._write('from :%d\n' % (base,))
        if merge is not None:
            for m in merge:
                self._write('merge :%d\n' % (m,))
        self._writelines(self.commit_info)
        self._write('\n')
        self.commit_info = []
        return mark

    def finish(self):
        """We are finished building, close the stream, get the id mapping"""
        self.stream.close()
        if self._process is None:
            return {}
        if self._process.wait() != 0:
            raise errors.GitCommandError(self._process.returncode,
                                         'git fast-import',
                                         self._process.stderr.read())
        marks_file = open(self._marks_file_name)
        mapping = {}
        for line in marks_file:
            mark, shasum = line.split()
            assert mark.startswith(':')
            mapping[int(mark[1:])] = shasum
        marks_file.close()
        return mapping


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
