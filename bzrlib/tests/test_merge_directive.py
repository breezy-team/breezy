from bzrlib import (
    errors,
    gpg,
    merge_directive,
    tests,
    )


class TestMergeDirective(tests.TestCase):

    def test_init(self):
        time = 500.0
        timezone = 5
        self.assertRaises(errors.NoMergeSource, merge_directive.MergeDirective,
            'example:', 'sha', time, timezone, 'http://example.com')
        self.assertRaises(errors.NoMergeSource, merge_directive.MergeDirective,
            'example:', 'sha', time, timezone, 'http://example.com',
            patch_type='diff')
        md = merge_directive.MergeDirective('example:', 'sha', time, timezone,
            'http://example.com', source_branch='http://example.org')
        self.assertRaises(errors.PatchMissing, merge_directive.MergeDirective,
            'example:', 'sha', time, timezone, 'http://example.com',
            patch_type='bundle')
        md = merge_directive.MergeDirective('null:', 'sha', time, timezone,
            'http://example.com', patch='blah', patch_type='bundle')
        self.assertRaises(errors.PatchMissing, merge_directive.MergeDirective,
            'example:', 'sha', time, timezone, 'http://example.com',
            source_branch="http://example.org", patch_type='diff')
        md = merge_directive.MergeDirective('example:', 'sha1', time, timezone,
            'http://example.com', source_branch="http://example.org",
            patch='', patch_type='diff')

    def test_serialization(self):
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


EMAIL1 = """To: pqm@example.com
From: J. Random Hacker <jrandom@example.com>
Subject: Commit of rev2a

# Bazaar merge directive format experimental-1
# revision_id: rev2a
# target_branch: (.|\n)*
# testament_sha1: .*
# timestamp: 1970-01-01 00:08:56 \\+0001
# source_branch: (.|\n)*
"""


EMAIL2 = """To: pqm@example.com
From: J. Random Hacker <jrandom@example.com>
Subject: Commit of rev2a with special message

# Bazaar merge directive format experimental-1
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

    def test_generate(self):
        tree_a, tree_b, branch_c = self.make_trees()
        self.assertRaises(errors.PublicBranchOutOfDate,
            merge_directive.MergeDirective.from_objects,
            tree_a.branch.repository, 'rev2a', 500, 144, tree_b.branch.base,
            public_branch=branch_c)
        md1 = merge_directive.MergeDirective.from_objects(
            tree_a.branch.repository, 'rev2a', 500, 144, tree_b.branch.base)
        self.assertContainsRe(md1.patch, 'Bazaar revision bundle')
        self.assertContainsRe(md1.patch, '\\+content_c')
        self.assertNotContainsRe(md1.patch, '\\+content_a')
        branch_c.pull(tree_a.branch)
        md2 = merge_directive.MergeDirective.from_objects(
            tree_a.branch.repository, 'rev2a', 500, 144, tree_b.branch.base,
            patch_type='diff', public_branch=branch_c)
        self.assertNotContainsRe(md2.patch, 'Bazaar revision bundle')
        self.assertContainsRe(md1.patch, '\\+content_c')
        self.assertNotContainsRe(md1.patch, '\\+content_a')
        md3 = merge_directive.MergeDirective.from_objects(
            tree_a.branch.repository, 'rev2a', 500, 144, tree_b.branch.base,
            patch_type=None, public_branch=branch_c, message='Merge message')
        md3.to_lines()
        self.assertIs(None, md3.patch)
        self.assertEqual('Merge message', md3.message)

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
            patch_type=None, public_branch=tree_a.branch)
        message = md.to_email('pqm@example.com', tree_a.branch)
        self.assertContainsRe(message.as_string(), EMAIL1)
        md.message = 'Commit of rev2a with special message'
        message = md.to_email('pqm@example.com', tree_a.branch)
        self.assertContainsRe(message.as_string(), EMAIL2)
