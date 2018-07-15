# Copyright (C) 2007, 2009 Canonical Ltd
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


from breezy import (
    merge_directive,
    tests,
    )


class TestBundleInfo(tests.TestCaseWithTransport):

    def test_bundle_info(self):
        source = self.make_branch_and_tree('source')
        self.build_tree(['source/foo'])
        source.add('foo')
        source.commit('added file', rev_id=b'rev1')
        with open('bundle', 'wb') as bundle:
            source.branch.repository.create_bundle(b'rev1', b'null:', bundle,
                                                   '4')
        info = self.run_bzr('bundle-info bundle')[0]
        # there might be either one file, or two, depending on whether the
        # tree root counts...
        self.assertContainsRe(info, 'file: [12] .0 multiparent.')
        self.assertContainsRe(info, 'nicks: source')
        self.assertNotContainsRe(info, 'foo')
        self.run_bzr_error(['--verbose requires a merge directive'],
                           'bundle-info -v bundle')
        target = self.make_branch('target')
        md = merge_directive.MergeDirective2.from_objects(
            source.branch.repository, b'rev1', 0, 0, 'target',
            base_revision_id=b'null:')
        with open('directive', 'wb') as directive:
            directive.writelines(md.to_lines())
        info = self.run_bzr('bundle-info -v directive')[0]
        self.assertContainsRe(info, 'foo')
