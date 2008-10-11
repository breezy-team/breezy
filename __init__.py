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

from bzrlib import commands, option


class cmd_shelve2(commands.Command):
    """Put some changes to the side for a while."""

    takes_args = ['file*']

    takes_options = [
        'revision',
        option.Option('all', help='Shelve all changes.'),
        'message',
    ]

    def run(self, revision=None, all=False, file_list=None, message=None):
        from bzrlib.plugins.shelf2.shelf_ui import Shelver
        Shelver.from_args(revision, all, file_list, message).run()


class cmd_unshelve2(commands.Command):
    """Restore shelved changes."""

    takes_args = ['shelf_id?']
    takes_options = [
        option.RegistryOption.from_kwargs(
            'action', enum_switch=False, value_switches=True,
            apply="Apply changes and remove from the shelf.",
            dry_run="Show changes, but do not apply or remove them.",
            delete_only="Delete changes without applying them."
        )
    ]

    def run(self, shelf_id=None, action='apply'):
        from bzrlib.plugins.shelf2.shelf_ui import Unshelver
        Unshelver.from_args(shelf_id, action).run()


commands.register_command(cmd_shelve2)
commands.register_command(cmd_unshelve2)


def test_suite():
    from bzrlib.plugins.shelf2 import tests
    return tests.test_suite()
