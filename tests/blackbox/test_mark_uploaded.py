#    test_mark_uploaded.py -- Blackbox tests for mark-uploaded.
#    Copyright (C) 2007 James Westby <jw+debian@jameswestby.net>
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
#

from __future__ import absolute_import

try:
    from debian.changelog import Changelog, Version
except ImportError:
    # Prior to 0.1.15 the debian module was called debian_bundle
    from debian_bundle.changelog import Changelog, Version

from .. import BuilddebTestCase


class TestMarkUploaded(BuilddebTestCase):

    def make_unuploaded(self):
        self.wt = self.make_branch_and_tree('.')
        self.build_tree(['debian/'])
        cl = Changelog()
        v = Version("0.1-1")
        cl.new_block(package='package',
                     version=Version('0.1-1'),
                     distributions='unstable',
                     urgency='low',
                     author='James Westby <jw+debian@jameswestby.net>',
                     date='Thu,  3 Aug 2006 19:16:22 +0100',
                     )
        cl.add_change('');
        cl.add_change('  * Initial packaging.');
        cl.add_change('');
        f = open('debian/changelog', 'wb')
        try:
            cl.write_to_open_file(f)
        finally:
            f.close()
        self.wt.add(["debian/", "debian/changelog"])
        self.wt.commit("one")

    def test_mark_uploaded_available(self):
        self.run_bzr('mark-uploaded --help')

    def test_mark_uploaded_changes(self):
        self.make_unuploaded()
        self.build_tree(['foo'])
        self.wt.add(['foo'])
        self.run_bzr_error(["There are uncommitted changes"],
                "mark-uploaded")

    def test_mark_uploaded_unkown_dist(self):
        self.make_unuploaded()
        cl = Changelog()
        v = Version("0.1-1")
        cl.new_block(package='package',
                     version=Version('0.1-1'),
                     distributions='UNRELEASED',
                     urgency='low',
                     author='James Westby <jw+debian@jameswestby.net>',
                     date='Thu,  3 Aug 2006 19:16:22 +0100',
                     )
        cl.add_change('');
        cl.add_change('  * Initial packaging.');
        cl.add_change('');
        f = open('debian/changelog', 'wb')
        try:
            cl.write_to_open_file(f)
        finally:
            f.close()
        self.wt.commit("two")
        self.run_bzr_error(["The changelog still targets 'UNRELEASED', so "
                "apparently hasn't been uploaded."], "mark-uploaded")

    def test_mark_uploaded_already(self):
        self.make_unuploaded()
        self.run_bzr("mark-uploaded")
        self.build_tree(["foo"])
        self.wt.add(["foo"])
        self.wt.commit("two")
        self.run_bzr_error(["This version has already been marked uploaded"],
                "mark-uploaded")

    def test_mark_uploaded(self):
        self.make_unuploaded()
        self.run_bzr("mark-uploaded")
        tagged_revision = self.wt.branch.tags.lookup_tag('0.1-1')
        self.assertEqual(tagged_revision, self.wt.branch.last_revision())

    def test_mark_uploaded_force(self):
        self.make_unuploaded()
        self.run_bzr("mark-uploaded")
        self.build_tree(["foo"])
        self.wt.add(["foo"])
        self.wt.commit("two")
        self.run_bzr("mark-uploaded --force")
        tagged_revision = self.wt.branch.tags.lookup_tag('0.1-1')
        self.assertEqual(tagged_revision, self.wt.branch.last_revision())
