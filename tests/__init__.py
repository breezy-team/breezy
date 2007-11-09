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


def test_suite():
    loader = tests.TestLoader()

    suite = tests.TestSuite()

    testmod_names = [
        'test_git_branch',
        'test_git_dir',
        'test_git_repository',
        'test_model',
        'test_ids',
        ]
    testmod_names = ['%s.%s' % (__name__, t) for t in testmod_names]
    suite.addTests(loader.loadTestsFromModuleNames(testmod_names))

    return suite
