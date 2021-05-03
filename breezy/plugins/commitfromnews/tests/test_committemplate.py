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

"""Tests for the commit template creation."""

from ... import commitfromnews
from .... import (
    config,
    msgeditor,
    )
from ....tests import TestCaseWithTransport

INITIAL_NEWS_CONTENT = b"""----------------------------
commitfromnews release notes
----------------------------

NEXT (In development)
---------------------

IMPROVEMENTS
~~~~~~~~~~~~

* Created plugin, basic functionality of looking for NEWS and including the
  NEWS diff.
"""


class TestCommitTemplate(TestCaseWithTransport):

    def capture_template(self, commit, message):
        self.commits.append(commit)
        self.messages.append(message)
        if message is None:
            message = u'let this commit succeed I command thee.'
        return message

    def enable_commitfromnews(self):
        stack = config.GlobalStack()
        stack.set("commit.template_from_files", ["NEWS"])

    def setup_capture(self):
        commitfromnews.register()
        msgeditor.hooks.install_named_hook('commit_message_template',
                                           self.capture_template, 'commitfromnews test template')
        self.messages = []
        self.commits = []

    def test_initial(self):
        self.setup_capture()
        self.enable_commitfromnews()
        builder = self.make_branch_builder('test')
        builder.start_series()
        builder.build_snapshot(None,
                               [('add', ('', None, 'directory', None)),
                                ('add', ('foo', b'foo-id', 'file', b'a\nb\nc\nd\ne\n')),
                                ],
                               message_callback=msgeditor.generate_commit_message_template,
                               revision_id=b'BASE-id')
        builder.finish_series()
        self.assertEqual([None], self.messages)

    def test_added_NEWS(self):
        self.setup_capture()
        self.enable_commitfromnews()
        builder = self.make_branch_builder('test')
        builder.start_series()
        content = INITIAL_NEWS_CONTENT
        builder.build_snapshot(None,
                               [('add', ('', None, 'directory', None)),
                                ('add', ('NEWS', b'foo-id', 'file', content)),
                                ],
                               message_callback=msgeditor.generate_commit_message_template,
                               revision_id=b'BASE-id')
        builder.finish_series()
        self.assertEqual([content.decode('utf-8')], self.messages)

    def test_changed_NEWS(self):
        self.setup_capture()
        self.enable_commitfromnews()
        builder = self.make_branch_builder('test')
        builder.start_series()
        orig_content = INITIAL_NEWS_CONTENT
        mod_content = b"""----------------------------
commitfromnews release notes
----------------------------

NEXT (In development)
---------------------

IMPROVEMENTS
~~~~~~~~~~~~

* Added a new change to the system.

* Created plugin, basic functionality of looking for NEWS and including the
  NEWS diff.
"""
        change_content = """* Added a new change to the system.

"""
        builder.build_snapshot(None,
                               [('add', ('', None, 'directory', None)),
                                ('add', ('NEWS', b'foo-id', 'file', orig_content)),
                                ], revision_id=b'BASE-id')
        builder.build_snapshot(None,
                               [('modify', ('NEWS', mod_content)),
                                ],
                               message_callback=msgeditor.generate_commit_message_template)
        builder.finish_series()
        self.assertEqual([change_content], self.messages)

    def test_fix_bug(self):
        self.setup_capture()
        self.enable_commitfromnews()
        builder = self.make_branch_builder('test')
        builder.start_series()
        orig_content = INITIAL_NEWS_CONTENT
        mod_content = b"""----------------------------
commitfromnews release notes
----------------------------

NEXT (In development)
---------------------

IMPROVEMENTS
~~~~~~~~~~~~

* Created plugin, basic functionality of looking for NEWS and including the
  NEWS diff.

* Fixed a horrible bug. (lp:523423)

"""
        change_content = """
* Fixed a horrible bug. (lp:523423)

"""
        builder.build_snapshot(None,
                               [('add', ('', None, 'directory', None)),
                                ('add', ('NEWS', b'foo-id', 'file', orig_content)),
                                ], revision_id=b'BASE-id')
        builder.build_snapshot(None,
                               [('modify', ('NEWS', mod_content)),
                                ],
                               message_callback=msgeditor.generate_commit_message_template)
        builder.finish_series()
        self.assertEqual([change_content], self.messages)
        self.assertEqual(1, len(self.commits))
        self.assertEquals('https://launchpad.net/bugs/523423 fixed',
                          self.commits[0].revprops['bugs'])

    def _todo_test_passes_messages_through(self):
        pass
