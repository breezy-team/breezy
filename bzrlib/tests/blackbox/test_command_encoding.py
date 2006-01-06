# Copyright (C) 2005 by Canonical Ltd
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

"""\
Tests for the Command.encoding_type interface.
"""

from bzrlib.tests import TestCase
from bzrlib.commands import Command, register_command, plugin_cmds

class cmd_echo_exact(Command):
    """This command just repeats what it is given.

    It decodes the argument, and then writes it to stdout.
    """

    takes_args = ['text']
    encoding_type = 'exact'

    def run(self, text=None):
        self.outf.write(text)


class cmd_echo_strict(cmd_echo_exact):
    """Replace bogus unicode characters."""

    encoding_type = 'strict'


class cmd_echo_replace(cmd_echo_exact):
    """Replace bogus unicode characters."""

    encoding_type = 'replace'


class TestCommandEncoding(TestCase):
    
    def test_exact(self):
        def bzr(*args, **kwargs):
            return self.run_bzr(*args, **kwargs)[0]

        register_command(cmd_echo_exact)
        try:
            self.assertEqual('foo', bzr('echo-exact', 'foo'))
            # This is cheating a little bit, because 'foo\xb5' shouldn't
            # get past main()
            self.assertEqual('foo\xb5', bzr('echo-exact', 'foo\xb5'))
            # Exact should fail to decode the string
            bzr('echo-exact', u'foo\xb5', retcode=3)
        finally:
            plugin_cmds.pop('echo-exact')

    def test_strict_utf8(self):
        def bzr(*args, **kwargs):
            kwargs['encoding'] = 'utf-8'
            return self.run_bzr(*args, **kwargs)[0]

        register_command(cmd_echo_strict)
        try:
            self.assertEqual('foo', bzr('echo-strict', 'foo'))
            self.assertEqual(u'foo\xb5'.encode('utf-8'),
                bzr('echo-strict', u'foo\xb5'))
        finally:
            plugin_cmds.pop('echo-strict')

    def test_strict_ascii(self):
        def bzr(*args, **kwargs):
            kwargs['encoding'] = 'ascii'
            return self.run_bzr(*args, **kwargs)[0]

        register_command(cmd_echo_strict)
        try:
            self.assertEqual('foo', bzr('echo-strict', 'foo'))
            # ascii can't encode \xb5
            bzr('echo-strict', u'foo\xb5', retcode=3)
        finally:
            plugin_cmds.pop('echo-strict')

    def test_replace_utf8(self):
        def bzr(*args, **kwargs):
            kwargs['encoding'] = 'utf-8'
            return self.run_bzr(*args, **kwargs)[0]

        register_command(cmd_echo_replace)
        try:
            self.assertEqual('foo', bzr('echo-replace', 'foo'))
            self.assertEqual(u'foo\xb5'.encode('utf-8'),
                             bzr('echo-replace', u'foo\xb5'))
        finally:
            plugin_cmds.pop('echo-replace')

    def test_replace_ascii(self):
        def bzr(*args, **kwargs):
            kwargs['encoding'] = 'ascii'
            return self.run_bzr(*args, **kwargs)[0]

        register_command(cmd_echo_replace)
        try:
            self.assertEqual('foo', bzr('echo-replace', 'foo'))
            # ascii can't encode \xb5
            self.assertEqual('foo?', bzr('echo-replace', u'foo\xb5'))
        finally:
            plugin_cmds.pop('echo-replace')


