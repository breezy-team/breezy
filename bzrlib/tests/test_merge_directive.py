from bzrlib import (
    errors,
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
            'http://example.com', public_location='http://example.org')
        self.assertRaises(errors.PatchMissing, merge_directive.MergeDirective,
            'example:', 'sha', time, timezone, 'http://example.com',
            patch_type='bundle')
        md = merge_directive.MergeDirective('null:', 'sha', time, timezone,
            'http://example.com', patch='blah', patch_type='bundle')
        self.assertRaises(errors.PatchMissing, merge_directive.MergeDirective,
            'example:', 'sha', time, timezone, 'http://example.com',
            public_location="http://example.org", patch_type='diff')
        md = merge_directive.MergeDirective('example:', 'sha1', time, timezone,
            'http://example.com', public_location="http://example.org",
            patch='', patch_type='diff')

    def test_serialization(self):
        time = 500.23
        timezone = 60
        md = merge_directive.MergeDirective('example:', 'sha', time, timezone,
            'http://example.com', public_location="http://example.org",
            patch='booga', patch_type='diff')
        md2 = merge_directive.MergeDirective.from_lines(md.to_lines())
        self.assertEqual('example:', md2.revision_id)
        self.assertEqual('sha', md2.testament_sha1)
        self.assertEqual('http://example.com', md2.submit_location)
        self.assertEqual('http://example.org', md2.public_location)
        self.assertEqual(time, md2.time)
        self.assertEqual(timezone, md2.timezone)
        self.assertEqual('diff', md2.patch_type)
        self.assertEqual('booga', md2.patch)
        md.patch = "# Bazaar revision bundle v0.9\n#\n"
        md3 = merge_directive.MergeDirective.from_lines(md.to_lines())
        self.assertEqual("# Bazaar revision bundle v0.9\n#\n", md3.patch)
        self.assertEqual("bundle", md3.patch_type)
        self.assertContainsRe(md3.to_lines()[0],
            '^# Bazaar merge directive format ')


class TestMergeDirectiveBranch(tests.TestCaseWithTransport):

    def test_generate(self):
        tree_a = self.make_branch_and_tree('tree_a')
        self.build_tree_contents([('tree_a/file', 'content_a\ncontent_b\n')])
        tree_a.add('file')
        tree_a.commit('message', rev_id='rev1')
        tree_b = tree_a.bzrdir.sprout('tree_b').open_workingtree()
        branch_c = tree_a.bzrdir.sprout('branch_c').open_branch()
        tree_b.commit('message', rev_id='rev2b')
        self.build_tree_contents([('tree_a/file', 'content_a\ncontent_c\n')])
        tree_a.commit('message', rev_id='rev2a')
        self.assertRaises(errors.PublicBranchOutOfDate,
            merge_directive.MergeDirective.from_objects,
            tree_a.branch.repository, 'rev2a', 500, 120, tree_b.branch.base,
            public_branch=branch_c)
        md1 = merge_directive.MergeDirective.from_objects(
            tree_a.branch.repository, 'rev2a', 500.0, 120, tree_b.branch.base)
        self.assertContainsRe(md1.patch, 'Bazaar revision bundle')
        self.assertContainsRe(md1.patch, '\\+content_c')
        self.assertNotContainsRe(md1.patch, '\\+content_a')
        branch_c.pull(tree_a.branch)
        md2 = merge_directive.MergeDirective.from_objects(
            tree_a.branch.repository, 'rev2a', 500.0, 120, tree_b.branch.base,
            patch_type='diff', public_branch=branch_c)
        self.assertNotContainsRe(md2.patch, 'Bazaar revision bundle')
        self.assertContainsRe(md1.patch, '\\+content_c')
        self.assertNotContainsRe(md1.patch, '\\+content_a')
        md3 = merge_directive.MergeDirective.from_objects(
            tree_a.branch.repository, 'rev2a', 500.0, 120, tree_b.branch.base,
            patch_type=None, public_branch=branch_c)
        md3.to_lines()
        self.assertIs(None, md3.patch)
