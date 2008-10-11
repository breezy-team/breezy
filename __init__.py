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
    """Temporarily set aside some changes from the current tree.

    Shelve allows you to temporarily put changes you've made "on the shelf",
    ie. out of the way, until a later time when you can bring them back from
    the shelf with the 'unshelve' command.

    Shelve is intended to help separate several sets of text changes that have
    been inappropriately mingled.  If you just want to get rid of all changes
    (text and otherwise) and you don't need to restore them later, use revert.
    If you want to shelve all text changes at once, use shelve --all.

    By default shelve asks you what you want to shelve, press '?' at the
    prompt to get help. To shelve everything run shelve --all.

    If filenames are specified, only the changes to those files will be
    shelved, other files will be left untouched.

    If a revision is specified, changes since that revision will be shelved.

    You can put multiple items on the shelf. Normally each time you run
    unshelve the most recently shelved changes will be reinstated. However,
    you can also unshelve changes in a different order by explicitly
    specifiying which changes to unshelve. This works best when the changes
    don't depend on each other.

    While you have patches on the shelf you can view and manipulate them with
    the 'shelf' command. Run 'bzr shelf -h' for more info.
    """

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
    """Restore shelved changes.

    By default the most recently shelved changes are restored. However if you
    specify a patch by name those changes will be restored instead.

    See 'shelve' for more information.
    """

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
