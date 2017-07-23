# Copyright (C) 2010 Canonical Ltd
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

"""bzr-commitfromnews - make commit messages from the changes in a NEWS file.

commitfromnews is enabled by default when installed.

To use, just do a commit where the NEWS file for your project has a new section
added without providing a message to commit.

E.g.::
  $ echo "\n* new thing\n" >> NEWS
  $ bzr commit
  # editor pops open to let you tweak the message, and it starts with
    "* new thing" as the message to edit.

commitfromnews attempts to create a sensible default commit message by
including sections from a NEWS or ChangeLog file.
"""

from __future__ import absolute_import

from ... import hooks


def commit_template(commit, message):
    """Create a commit message for commit based on changes in the tree."""
    from .committemplate import CommitTemplate
    template = CommitTemplate(commit, message)
    return template.make()


def load_tests(loader, basic_tests, pattern):
    testmod_names = [
        'tests',
        ]
    basic_tests.addTest(loader.loadTestsFromModuleNames(
            ["%s.%s" % (__name__, tmn) for tmn in testmod_names]))
    return basic_tests


_registered = False


def register():
    """Register the plugin."""
    global _registered
    # Does not check registered because only tests call this, and they are
    # isolated.
    _registered = True
    hooks.install_lazy_named_hook(
        'breezy.msgeditor', 'hooks',
        'commit_message_template',
        commit_template, 'commitfromnews template')


register()
