# Copyright (C) 2007 Canonical Ltd
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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA


from bzrlib import (
    errors,
    gpg,
    merge_directive,
    tests,
    )


OUTPUT1 = """# Bazaar merge directive format 1
# revision_id: example:
# target_branch: http://example.com
# testament_sha1: sha
# timestamp: 1970-01-01 00:09:33 +0002
#\x20
booga"""


OUTPUT2 = """# Bazaar merge directive format 1
# revision_id: example:
# target_branch: http://example.com
# testament_sha1: sha
# timestamp: 1970-01-01 00:09:33 +0002
# source_branch: http://example.org
# message: Hi mom!
#\x20
booga"""


INPUT1 = """
I was thinking today about creating a merge directive.

So I did.

Here it is.

(I've pasted it in the body of this message)

Aaron

# Bazaar merge directive format 1\r
# revision_id: example:
# target_branch: http://example.com
# testament_sha1: sha
# timestamp: 1970-01-01 00:09:33 +0002
# source_branch: http://example.org
# message: Hi mom!
#\x20
booga""".splitlines(True)


class TestMergeDirective(tests.TestCase):

    def test_merge_source(self):
        time = 500.0
        timezone = 5
        self.assertRaises(errors.NoMergeSource, merge_directive.MergeDirective,
            'example:', 'sha', time, timezone, 'http://example.com')
        self.assertRaises(errors.NoMergeSource, merge_directive.MergeDirective,
            'example:', 'sha', time, timezone, 'http://example.com',
            patch_type='diff')
        merge_directive.MergeDirective('example:', 'sha', time, timezone,
            'http://example.com', source_branch='http://example.org')
        md = merge_directive.MergeDirective('null:', 'sha', time, timezone,
            'http://example.com', patch='blah', patch_type='bundle')
        self.assertIs(None, md.source_branch)
        md2 = merge_directive.MergeDirective('null:', 'sha', time, timezone,
            'http://example.com', patch='blah', patch_type='bundle',
            source_branch='bar')
        self.assertEqual('bar', md2.source_branch)

    def test_require_patch(self):
        time = 500.0
        timezone = 5
        self.assertRaises(errors.PatchMissing, merge_directive.MergeDirective,
            'example:', 'sha', time, timezone, 'http://example.com',
            patch_type='bundle')
        md = merge_directive.MergeDirective('example:', 'sha1', time, timezone,
            'http://example.com', source_branch="http://example.org",
            patch='', patch_type='diff')
        self.assertEqual(md.patch, '')

    def test_serialization(self):
        time = 501
        timezone = 72
        md = merge_directive.MergeDirective('example:', 'sha', time, timezone,
            'http://example.com', patch='booga', patch_type='bundle')
        self.assertEqualDiff(OUTPUT1, ''.join(md.to_lines()))
        md = merge_directive.MergeDirective('example:', 'sha', time, timezone,
            'http://example.com', source_branch="http://example.org",
            patch='booga', patch_type='diff', message="Hi mom!")
        self.assertEqualDiff(OUTPUT2, ''.join(md.to_lines()))

    def test_deserialize_junk(self):
        self.assertRaises(errors.NotAMergeDirective,
                          merge_directive.MergeDirective.from_lines, 'lala')

    def test_deserialize_leading_junk(self):
        md = merge_directive.MergeDirective.from_lines(INPUT1)
        self.assertEqual('example:', md.revision_id)
        self.assertEqual('sha', md.testament_sha1)
        self.assertEqual('http://example.com', md.target_branch)
        self.assertEqual('http://example.org', md.source_branch)
        self.assertEqual(501, md.time)
        self.assertEqual(72, md.timezone)
        self.assertEqual('booga', md.patch)
        self.assertEqual('diff', md.patch_type)
        self.assertEqual('Hi mom!', md.message)

    def test_roundtrip(self):
        time = 501
        timezone = 72
        md = merge_directive.MergeDirective('example:', 'sha', time, timezone,
            'http://example.com', source_branch="http://example.org",
            patch='booga', patch_type='diff')
        md2 = merge_directive.MergeDirective.from_lines(md.to_lines())
        self.assertEqual('example:', md2.revision_id)
        self.assertEqual('sha', md2.testament_sha1)
        self.assertEqual('http://example.com', md2.target_branch)
        self.assertEqual('http://example.org', md2.source_branch)
        self.assertEqual(time, md2.time)
        self.assertEqual(timezone, md2.timezone)
        self.assertEqual('diff', md2.patch_type)
        self.assertEqual('booga', md2.patch)
        self.assertEqual(None, md2.message)
        md.patch = "# Bazaar revision bundle v0.9\n#\n"
        md.message = "Hi mom!"
        md3 = merge_directive.MergeDirective.from_lines(md.to_lines())
        self.assertEqual("# Bazaar revision bundle v0.9\n#\n", md3.patch)
        self.assertEqual("bundle", md3.patch_type)
        self.assertContainsRe(md3.to_lines()[0],
            '^# Bazaar merge directive format ')
        self.assertEqual("Hi mom!", md3.message)
        md3.patch_type = None
        md3.patch = None
        md4 = merge_directive.MergeDirective.from_lines(md3.to_lines())
        self.assertIs(None, md4.patch_type)


EMAIL1 = """To: pqm@example.com
From: J. Random Hacker <jrandom@example.com>
Subject: Commit of rev2a

# Bazaar merge directive format 1
# revision_id: rev2a
# target_branch: (.|\n)*
# testament_sha1: .*
# timestamp: 1970-01-01 00:08:56 \\+0001
# source_branch: (.|\n)*
"""


EMAIL2 = """To: pqm@example.com
From: J. Random Hacker <jrandom@example.com>
Subject: Commit of rev2a with special message

# Bazaar merge directive format 1
# revision_id: rev2a
# target_branch: (.|\n)*
# testament_sha1: .*
# timestamp: 1970-01-01 00:08:56 \\+0001
# source_branch: (.|\n)*
# message: Commit of rev2a with special message
"""


class TestMergeDirectiveBranch(tests.TestCaseWithTransport):

    def make_trees(self):
        tree_a = self.make_branch_and_tree('tree_a')
        tree_a.branch.get_config().set_user_option('email',
            'J. Random Hacker <jrandom@example.com>')
        self.build_tree_contents([('tree_a/file', 'content_a\ncontent_b\n')])
        tree_a.add('file')
        tree_a.commit('message', rev_id='rev1')
        tree_b = tree_a.bzrdir.sprout('tree_b').open_workingtree()
        branch_c = tree_a.bzrdir.sprout('branch_c').open_branch()
        tree_b.commit('message', rev_id='rev2b')
        self.build_tree_contents([('tree_a/file', 'content_a\ncontent_c\n')])
        tree_a.commit('Commit of rev2a', rev_id='rev2a')
        return tree_a, tree_b, branch_c

    def test_generate_patch(self):
        tree_a, tree_b, branch_c = self.make_trees()
        md2 = merge_directive.MergeDirective.from_objects(
            tree_a.branch.repository, 'rev2a', 500, 144, tree_b.branch.base,
            patch_type='diff', public_branch=tree_a.branch.base)
        self.assertNotContainsRe(md2.patch, 'Bazaar revision bundle')
        self.assertContainsRe(md2.patch, '\\+content_c')
        self.assertNotContainsRe(md2.patch, '\\+\\+\\+ b/')
        self.assertContainsRe(md2.patch, '\\+\\+\\+ file')

    def test_public_branch(self):
        tree_a, tree_b, branch_c = self.make_trees()
        self.assertRaises(errors.PublicBranchOutOfDate,
            merge_directive.MergeDirective.from_objects,
            tree_a.branch.repository, 'rev2a', 500, 144, tree_b.branch.base,
            public_branch=branch_c.base, patch_type='diff')
        # public branch is not checked if patch format is bundle.
        md1 = merge_directive.MergeDirective.from_objects(
            tree_a.branch.repository, 'rev2a', 500, 144, tree_b.branch.base,
            public_branch=branch_c.base)
        # public branch is provided with a bundle, despite possibly being out
        # of date, because it's not required if a bundle is present.
        self.assertEqual(md1.source_branch, branch_c.base)
        # Once we update the public branch, we can generate a diff.
        branch_c.pull(tree_a.branch)
        md3 = merge_directive.MergeDirective.from_objects(
            tree_a.branch.repository, 'rev2a', 500, 144, tree_b.branch.base,
            patch_type=None, public_branch=branch_c.base)

    def test_use_public_submit_branch(self):
        tree_a, tree_b, branch_c = self.make_trees()
        branch_c.pull(tree_a.branch)
        md = merge_directive.MergeDirective.from_objects(
             tree_a.branch.repository, 'rev2a', 500, 144, tree_b.branch.base,
             patch_type=None, public_branch=branch_c.base)
        self.assertEqual(md.target_branch, tree_b.branch.base)
        tree_b.branch.set_public_branch('http://example.com')
        md2 = merge_directive.MergeDirective.from_objects(
              tree_a.branch.repository, 'rev2a', 500, 144, tree_b.branch.base,
              patch_type=None, public_branch=branch_c.base)
        self.assertEqual(md2.target_branch, 'http://example.com')

    def test_message(self):
        tree_a, tree_b, branch_c = self.make_trees()
        md3 = merge_directive.MergeDirective.from_objects(
            tree_a.branch.repository, 'rev2a', 500, 144, tree_b.branch.base,
            patch_type=None, public_branch=branch_c.base,
            message='Merge message')
        md3.to_lines()
        self.assertIs(None, md3.patch)
        self.assertEqual('Merge message', md3.message)

    def test_generate_bundle(self):
        tree_a, tree_b, branch_c = self.make_trees()
        md1 = merge_directive.MergeDirective.from_objects(
            tree_a.branch.repository, 'rev2a', 500, 144, tree_b.branch.base,
            public_branch=branch_c.base)
        self.assertContainsRe(md1.patch, 'Bazaar revision bundle')
        self.assertContainsRe(md1.patch, '\\+content_c')
        self.assertNotContainsRe(md1.patch, '\\+content_a')
        self.assertContainsRe(md1.patch, '\\+content_c')
        self.assertNotContainsRe(md1.patch, '\\+content_a')

    def test_signing(self):
        time = 501
        timezone = 72
        class FakeBranch(object):
            def get_config(self):
                return self
            def gpg_signing_command(self):
                return 'loopback'
        md = merge_directive.MergeDirective('example:', 'sha', time, timezone,
            'http://example.com', source_branch="http://example.org",
            patch='booga', patch_type='diff')
        old_strategy = gpg.GPGStrategy
        gpg.GPGStrategy = gpg.LoopbackGPGStrategy
        try:
            signed = md.to_signed(FakeBranch())
        finally:
            gpg.GPGStrategy = old_strategy
        self.assertContainsRe(signed, '^-----BEGIN PSEUDO-SIGNED CONTENT')
        self.assertContainsRe(signed, 'example.org')
        self.assertContainsRe(signed, 'booga')

    def test_email(self):
        tree_a, tree_b, branch_c = self.make_trees()
        md = merge_directive.MergeDirective.from_objects(
            tree_a.branch.repository, 'rev2a', 500, 36, tree_b.branch.base,
            patch_type=None, public_branch=tree_a.branch.base)
        message = md.to_email('pqm@example.com', tree_a.branch)
        self.assertContainsRe(message.as_string(), EMAIL1)
        md.message = 'Commit of rev2a with special message'
        message = md.to_email('pqm@example.com', tree_a.branch)
        self.assertContainsRe(message.as_string(), EMAIL2)
