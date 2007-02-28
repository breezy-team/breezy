from bzrlib import (
    errors,
    merge_directive,
    tests,
    )

class TestMergeDirective(tests.TestCase):

    def test_init(self):
        self.assertRaises(errors.NoMergeSource, merge_directive.MergeDirective,
            'example:', 'sha', 'http://example.com')
        self.assertRaises(errors.NoMergeSource, merge_directive.MergeDirective,
            'example:', 'sha', 'http://example.com', patch_type='diff')
        md = merge_directive.MergeDirective('example:', 'sha',
            'http://example.com', public_location='http://example.org')
        self.assertRaises(errors.PatchMissing, merge_directive.MergeDirective,
            'example:', 'sha', 'http://example.com', patch_type='bundle')
        md = merge_directive.MergeDirective('null:', 'sha',
            'http://example.com', patch='blah', patch_type='bundle')
        self.assertRaises(errors.PatchMissing, merge_directive.MergeDirective,
            'example:', 'http://example.com', 'sha',
            public_location="http://example.org", patch_type='diff')
        md = merge_directive.MergeDirective('example:',
            'sha1', 'http://example.com', public_location="http://example.org",
            patch='', patch_type='diff')

    def test_serialization(self):
        md = merge_directive.MergeDirective('example:', 'sha',
            'http://example.com', public_location="http://example.org",
            patch='booga', patch_type='diff')
        md2 = merge_directive.MergeDirective.from_lines(md.to_lines())
        self.assertEqual('example:', md2.revision)
        self.assertEqual('sha', md2.testament_sha1)
        self.assertEqual('http://example.com', md2.submit_location)
        self.assertEqual('http://example.org', md2.public_location)
        self.assertEqual('diff', md2.patch_type)
        self.assertEqual('booga', md2.patch)
        md.patch = "# Bazaar revision bundle v0.9\n#\n"
        md3 = merge_directive.MergeDirective.from_lines(md.to_lines())
        self.assertEqual("# Bazaar revision bundle v0.9\n#\n", md3.patch)
        self.assertEqual("bundle", md3.patch_type)
