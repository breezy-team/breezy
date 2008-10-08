# Copyright (C) 2008 Aaron Bentley <aaron@aaronbentley.com>
#
#    This program is free software; you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation; either version 2 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program; if not, write to the Free Software
#    Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Reimplementation of shelf commands."""

from bzrlib import commands


class cmd_shelve2(commands.Command):
    """Put some changes to the side for a while."""

    takes_options = [
        'revision',
        commands.Option('all', help='Shelve all changes.')]

    def run(self, revision=None, all=False):
        from bzrlib.plugins.shelf2.shelver import Shelver
        Shelver.from_args(revision, all).run()

class cmd_unshelve2(commands.Command):
    """Restore shelved changes."""

    def run(self):
        from bzrlib.plugins.shelf2.shelver import Unshelver
        Unshelver.from_args().run()


commands.register_command(cmd_shelve2)
commands.register_command(cmd_unshelve2)


def test_suite():
    from bzrlib.plugins.shelf2 import tests
    return tests.test_suite()
