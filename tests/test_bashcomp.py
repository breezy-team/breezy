# Copyright (C) 2010 by Canonical Ltd
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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

from bzrlib.tests import TestCase, Feature
from bzrlib import commands
from StringIO import StringIO
from ..bashcomp import bash_completion_function
import os
import subprocess


class _BashFeature(Feature):

    bash_paths = ['/bin/bash', '/usr/bin/bash']

    def __init__(self):
        super(_BashFeature, self).__init__()
        self.bash_path = None

    def available(self):
        if self.bash_path is not None:
            return self.bash_path is not False
        for path in self.bash_paths:
            if os.access(path, os.X_OK):
                self.bash_path = path
                return True
        self.bash_path = False
        return False

    def feature_name(self):
        return 'bash'

BashFeature = _BashFeature()


class TestBashCompletion(TestCase):

    _test_needs_features = [BashFeature]

    def __init__(self, methodName='testMethod'):
        super(TestBashCompletion, self).__init__(methodName)
        self.script = None

    def setUp(self):
        super(TestBashCompletion, self).setUp()
        commands.install_bzr_command_hooks()

    def complete(self, words, cword=-1, expect=None,
                 contains=[], omits=[]):
        if self.script is None:
            self.script = self.get_script()
        proc = subprocess.Popen([BashFeature.bash_path, '--noprofile'],
                                stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE)
        if cword < 0:
            cword = len(words) + cword
        input = """
%(script)s

COMP_WORDS=( %(words)s )
COMP_CWORD=%(cword)d
%(name)s
echo ${#COMPREPLY[*]}
IFS=$'\\n'
echo "${COMPREPLY[*]}"
""" % { 'script': self.script,
        'words': ' '.join(["'"+w.replace("'", "'\\''")+"'" for w in words]),
        'cword': cword,
        'name': getattr(self, 'script_name', '_bzr'),
      }
        (out, err) = proc.communicate(input)
        self.assertEqual('', err, 'No messages to standard error')
        #import sys
        #print >>sys.stdout, '---\n%s\n---\n%s\n---\n' % (input, out)
        lines = out.split('\n')
        nlines = int(lines[0])
        del lines[0]
        self.assertEqual('', lines[-1], 'Newline at end')
        del lines[-1]
        if nlines == 0 and len(lines) == 1 and lines[0] == '':
            del lines[0]
        self.assertEqual(nlines, len(lines), 'No newlines in generated words')
        if expect is not None:
            self.assertEqual(expect, lines)
        for item in contains:
            self.assertTrue(item in lines)
        for item in omits:
            self.assertFalse(item in lines)
        return lines

    def get_script(self):
        out = StringIO()
        bash_completion_function(out, function_only=True)
        return out.getvalue()

    def test_simple_scipt(self):
        """Ensure that the test harness works as expected"""
        self.script = """
_bzr() {
    COMPREPLY=()
    # add all words in reverse order, with some markup around them
    for ((i = ${#COMP_WORDS[@]}; i > 0; --i)); do
        COMPREPLY+=( "-${COMP_WORDS[i-1]}+" )
    done
    # and append the current word
    COMPREPLY+=( "+${COMP_WORDS[COMP_CWORD]}-" )
}
"""
        self.complete(['foo', '"bar', "'baz"], cword=1,
                      expect=["-'baz+", '-"bar+', '-foo+', '+"bar-'])

    def test_cmd_ini(self):
        c = self.complete(['bzr', 'ini'],
                          contains=['init', 'init-repo', 'init-repository'])
        self.assertFalse('commit' in c)

    def test_init_opts(self):
        c = self.complete(['bzr', 'init', '-'],
                          contains=['-h', '--2a', '--format=2a'])

    def test_global_opts(self):
        c = self.complete(['bzr', '-', 'init'], cword=1,
                          contains=['--no-plugins', '-?'])

    def test_commit_dashm(self):
        c = self.complete(['bzr', 'commit', '-m'], expect=['-m'])

    def test_status_negated(self):
        c = self.complete(['bzr', 'status', '--n'],
                          contains=['--no-versioned', '--no-verbose'])

    def test_init_format_any(self):
        c = self.complete(['bzr', 'init', '--format', '=', 'directory'],
                          cword=3, contains=['1.9', '2a'])

    def test_init_format_2(self):
        c = self.complete(['bzr', 'init', '--format', '=', '2', 'directory'],
                          cword=4, contains=['2a'], omits=['1.9'])
