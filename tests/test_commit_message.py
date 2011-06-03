#    test_comit_message.py -- Test hook for pre-filling commit message.
#    Copyright (C) 2009 Canonical Ltd.
#
#    This file is part of bzr-builddeb.
#
#    bzr-builddeb is free software; you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation; either version 2 of the License, or
#    (at your option) any later version.
#
#    bzr-builddeb is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with bzr-builddeb; if not, write to the Free Software
#    Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA

from bzrlib.tests import TestCaseWithTransport

from bzrlib.plugins.builddeb import debian_changelog_commit_message, debian_changelog_commit


class CommitMessageTests(TestCaseWithTransport):

    class _Commit(object):
        class _Builder(object):
            _revprops = {}
        def __init__(self, work_tree, exclude=[], specific_files=[]):
            self.work_tree = work_tree
            self.exclude = exclude
            self.specific_files = specific_files
            self.builder = self._Builder()

    def set_changelog_content(self, content):
        f = open("debian/changelog", 'wb')
        try:
            f.write(content)
        finally:
            f.close()

    def test_leaves_existing_message(self):
        self.assertEqual(debian_changelog_commit_message(None, "foo"), "foo")

    def test_ignores_commit_without_debian_changelog(self):
        wt = self.make_branch_and_tree(".")
        self.build_tree(['a'])
        wt.add(['a'])
        wt.lock_read()
        self.addCleanup(wt.unlock)
        commit = self._Commit(wt)
        self.assertEqual(debian_changelog_commit_message(commit, None), None)

    def test_ignores_commit_excluding_debian_changelog(self):
        wt = self.make_branch_and_tree(".")
        self.build_tree(['debian/', 'debian/changelog'])
        wt.add(['debian/', 'debian/changelog'])
        wt.commit("one")
        self.set_changelog_content("  * new line")
        wt.lock_read()
        self.addCleanup(wt.unlock)
        commit = self._Commit(wt, exclude=["debian/changelog"])
        self.assertEqual(debian_changelog_commit_message(commit, None), None)

    def test_ignores_commit_specific_files(self):
        wt = self.make_branch_and_tree(".")
        self.build_tree(['a', 'debian/', 'debian/changelog'])
        wt.add(['debian/', 'debian/changelog'])
        wt.commit("one")
        self.set_changelog_content("  * new line\n")
        wt.add(['a'])
        wt.lock_read()
        self.addCleanup(wt.unlock)
        commit = self._Commit(wt, specific_files=["a"])
        self.assertEqual(debian_changelog_commit_message(commit, None), None)

    def test_provides_stripped_message(self):
        wt = self.make_branch_and_tree(".")
        self.build_tree(['a', 'debian/', 'debian/changelog'])
        wt.add(['debian/', 'debian/changelog'])
        wt.commit("one")
        self.set_changelog_content("  * new line\n")
        wt.add(['a'])
        wt.lock_read()
        self.addCleanup(wt.unlock)
        commit = self._Commit(wt)
        self.assertEqual(debian_changelog_commit_message(commit, None),
                "new line\n")

    def test_provides_unstripped_message(self):
        wt = self.make_branch_and_tree(".")
        self.build_tree(['a', 'debian/', 'debian/changelog'])
        wt.add(['debian/', 'debian/changelog'])
        wt.commit("one")
        self.set_changelog_content("  * two\n  * changes\n")
        wt.add(['a'])
        wt.lock_read()
        self.addCleanup(wt.unlock)
        commit = self._Commit(wt)
        self.assertEqual(debian_changelog_commit_message(commit, None),
                "* two\n* changes\n")

    def test_set_message_with_bugs(self):
        wt = self.make_branch_and_tree(".")
        self.build_tree(['a', 'debian/', 'debian/changelog'])
        wt.add(['debian/', 'debian/changelog'])
        wt.commit("one")
        self.set_changelog_content("  * fix LP: #1234\n  * close LP: #4321\n")
        wt.add(['a'])
        wt.lock_read()
        self.addCleanup(wt.unlock)
        commit = self._Commit(wt)
        self.assertEqual(debian_changelog_commit(commit, None),
                "* fix LP: #1234\n* close LP: #4321\n")
        self.assertEqual(commit.builder._revprops, {'bugs': 'https://launchpad.net/bugs/1234 fixed\nhttps://launchpad.net/bugs/4321 fixed\n'})
