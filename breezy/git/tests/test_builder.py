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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

"""Test our ability to build up test repositories"""

from io import BytesIO

from dulwich.repo import Repo as GitRepo

from .. import tests


class TestGitBranchBuilder(tests.TestCase):

    def test__create_blob(self):
        stream = BytesIO()
        builder = tests.GitBranchBuilder(stream)
        self.assertEqual(1, builder._create_blob(b'foo\nbar\n'))
        self.assertEqualDiff(b'blob\nmark :1\ndata 8\nfoo\nbar\n\n',
                             stream.getvalue())

    def test_set_file(self):
        stream = BytesIO()
        builder = tests.GitBranchBuilder(stream)
        builder.set_file('foobar', b'foo\nbar\n', False)
        self.assertEqualDiff(b'blob\nmark :1\ndata 8\nfoo\nbar\n\n',
                             stream.getvalue())
        self.assertEqual([b'M 100644 :1 foobar\n'], builder.commit_info)

    def test_set_file_unicode(self):
        stream = BytesIO()
        builder = tests.GitBranchBuilder(stream)
        builder.set_file(u'f\xb5/bar', b'contents\nbar\n', False)
        self.assertEqualDiff(b'blob\nmark :1\ndata 13\ncontents\nbar\n\n',
                             stream.getvalue())
        self.assertEqual([b'M 100644 :1 f\xc2\xb5/bar\n'], builder.commit_info)

    def test_set_file_newline(self):
        stream = BytesIO()
        builder = tests.GitBranchBuilder(stream)
        builder.set_file(u'foo\nbar', b'contents\nbar\n', False)
        self.assertEqualDiff(b'blob\nmark :1\ndata 13\ncontents\nbar\n\n',
                             stream.getvalue())
        self.assertEqual([b'M 100644 :1 "foo\\nbar"\n'], builder.commit_info)

    def test_set_file_executable(self):
        stream = BytesIO()
        builder = tests.GitBranchBuilder(stream)
        builder.set_file(u'f\xb5/bar', b'contents\nbar\n', True)
        self.assertEqualDiff(b'blob\nmark :1\ndata 13\ncontents\nbar\n\n',
                             stream.getvalue())
        self.assertEqual([b'M 100755 :1 f\xc2\xb5/bar\n'], builder.commit_info)

    def test_set_symlink(self):
        stream = BytesIO()
        builder = tests.GitBranchBuilder(stream)
        builder.set_symlink(u'f\xb5/bar', b'link/contents')
        self.assertEqualDiff(b'blob\nmark :1\ndata 13\nlink/contents\n',
                             stream.getvalue())
        self.assertEqual([b'M 120000 :1 f\xc2\xb5/bar\n'], builder.commit_info)

    def test_set_symlink_newline(self):
        stream = BytesIO()
        builder = tests.GitBranchBuilder(stream)
        builder.set_symlink(u'foo\nbar', 'link/contents')
        self.assertEqualDiff(b'blob\nmark :1\ndata 13\nlink/contents\n',
                             stream.getvalue())
        self.assertEqual([b'M 120000 :1 "foo\\nbar"\n'], builder.commit_info)

    def test_delete_entry(self):
        stream = BytesIO()
        builder = tests.GitBranchBuilder(stream)
        builder.delete_entry(u'path/to/f\xb5')
        self.assertEqual([b'D path/to/f\xc2\xb5\n'], builder.commit_info)

    def test_delete_entry_newline(self):
        stream = BytesIO()
        builder = tests.GitBranchBuilder(stream)
        builder.delete_entry(u'path/to/foo\nbar')
        self.assertEqual([b'D "path/to/foo\\nbar"\n'], builder.commit_info)

    def test_encode_path(self):
        encode = tests.GitBranchBuilder._encode_path
        # Unicode is encoded to utf-8
        self.assertEqual(encode(u'f\xb5'), b'f\xc2\xb5')
        # The name must be quoted if it starts by a double quote or contains a
        # newline.
        self.assertEqual(encode(u'"foo'), b'"\\"foo"')
        self.assertEqual(encode(u'fo\no'), b'"fo\\no"')
        # When the name is quoted, all backslash and quote chars must be
        # escaped.
        self.assertEqual(encode(u'fo\\o\nbar'), b'"fo\\\\o\\nbar"')
        self.assertEqual(encode(u'fo"o"\nbar'), b'"fo\\"o\\"\\nbar"')
        # Other control chars, such as \r, need not be escaped.
        self.assertEqual(encode(u'foo\r\nbar'), b'"foo\r\\nbar"')

    def test_add_and_commit(self):
        stream = BytesIO()
        builder = tests.GitBranchBuilder(stream)

        builder.set_file(u'f\xb5/bar', b'contents\nbar\n', False)
        self.assertEqual(b'2', builder.commit(b'Joe Foo <joe@foo.com>',
                                              u'committing f\xb5/bar',
                                              timestamp=1194586400,
                                              timezone=b'+0100'))
        self.assertEqualDiff(b'blob\nmark :1\ndata 13\ncontents\nbar\n\n'
                             b'commit refs/heads/master\n'
                             b'mark :2\n'
                             b'committer Joe Foo <joe@foo.com> 1194586400 +0100\n'
                             b'data 18\n'
                             b'committing f\xc2\xb5/bar'
                             b'\n'
                             b'M 100644 :1 f\xc2\xb5/bar\n'
                             b'\n',
                             stream.getvalue())

    def test_commit_base(self):
        stream = BytesIO()
        builder = tests.GitBranchBuilder(stream)

        builder.set_file(u'foo', b'contents\nfoo\n', False)
        r1 = builder.commit(b'Joe Foo <joe@foo.com>', u'first',
                            timestamp=1194586400)
        r2 = builder.commit(b'Joe Foo <joe@foo.com>', u'second',
                            timestamp=1194586405)
        r3 = builder.commit(b'Joe Foo <joe@foo.com>', u'third',
                            timestamp=1194586410,
                            base=r1)

        self.assertEqualDiff(b'blob\nmark :1\ndata 13\ncontents\nfoo\n\n'
                             b'commit refs/heads/master\n'
                             b'mark :2\n'
                             b'committer Joe Foo <joe@foo.com> 1194586400 +0000\n'
                             b'data 5\n'
                             b'first'
                             b'\n'
                             b'M 100644 :1 foo\n'
                             b'\n'
                             b'commit refs/heads/master\n'
                             b'mark :3\n'
                             b'committer Joe Foo <joe@foo.com> 1194586405 +0000\n'
                             b'data 6\n'
                             b'second'
                             b'\n'
                             b'\n'
                             b'commit refs/heads/master\n'
                             b'mark :4\n'
                             b'committer Joe Foo <joe@foo.com> 1194586410 +0000\n'
                             b'data 5\n'
                             b'third'
                             b'\n'
                             b'from :2\n'
                             b'\n', stream.getvalue())

    def test_commit_merge(self):
        stream = BytesIO()
        builder = tests.GitBranchBuilder(stream)

        builder.set_file(u'foo', b'contents\nfoo\n', False)
        r1 = builder.commit(b'Joe Foo <joe@foo.com>', u'first',
                            timestamp=1194586400)
        r2 = builder.commit(b'Joe Foo <joe@foo.com>', u'second',
                            timestamp=1194586405)
        r3 = builder.commit(b'Joe Foo <joe@foo.com>', u'third',
                            timestamp=1194586410,
                            base=r1)
        r4 = builder.commit(b'Joe Foo <joe@foo.com>', u'Merge',
                            timestamp=1194586415,
                            merge=[r2])

        self.assertEqualDiff(b'blob\nmark :1\ndata 13\ncontents\nfoo\n\n'
                             b'commit refs/heads/master\n'
                             b'mark :2\n'
                             b'committer Joe Foo <joe@foo.com> 1194586400 +0000\n'
                             b'data 5\n'
                             b'first'
                             b'\n'
                             b'M 100644 :1 foo\n'
                             b'\n'
                             b'commit refs/heads/master\n'
                             b'mark :3\n'
                             b'committer Joe Foo <joe@foo.com> 1194586405 +0000\n'
                             b'data 6\n'
                             b'second'
                             b'\n'
                             b'\n'
                             b'commit refs/heads/master\n'
                             b'mark :4\n'
                             b'committer Joe Foo <joe@foo.com> 1194586410 +0000\n'
                             b'data 5\n'
                             b'third'
                             b'\n'
                             b'from :2\n'
                             b'\n'
                             b'commit refs/heads/master\n'
                             b'mark :5\n'
                             b'committer Joe Foo <joe@foo.com> 1194586415 +0000\n'
                             b'data 5\n'
                             b'Merge'
                             b'\n'
                             b'merge :3\n'
                             b'\n', stream.getvalue())

    def test_auto_timestamp(self):
        stream = BytesIO()
        builder = tests.GitBranchBuilder(stream)
        builder.commit(b'Joe Foo <joe@foo.com>', u'message')
        self.assertContainsRe(stream.getvalue(),
                              br'committer Joe Foo <joe@foo\.com> \d+ \+0000')

    def test_reset(self):
        stream = BytesIO()
        builder = tests.GitBranchBuilder(stream)
        builder.reset()
        self.assertEqualDiff(b'reset refs/heads/master\n\n', stream.getvalue())

    def test_reset_named_ref(self):
        stream = BytesIO()
        builder = tests.GitBranchBuilder(stream)
        builder.reset(b'refs/heads/branch')
        self.assertEqualDiff(b'reset refs/heads/branch\n\n', stream.getvalue())

    def test_reset_revision(self):
        stream = BytesIO()
        builder = tests.GitBranchBuilder(stream)
        builder.reset(mark=b'123')
        self.assertEqualDiff(
            b'reset refs/heads/master\n'
            b'from :123\n'
            b'\n', stream.getvalue())


class TestGitBranchBuilderReal(tests.TestCaseInTempDir):

    def test_create_real_branch(self):
        GitRepo.init(".")

        builder = tests.GitBranchBuilder()
        builder.set_file(u'foo', b'contents\nfoo\n', False)
        r1 = builder.commit(b'Joe Foo <joe@foo.com>', u'first',
                            timestamp=1194586400)
        mapping = builder.finish()
        self.assertEqual({b'1': b'44411e8e9202177dd19b6599d7a7991059fa3cb4',
                          b'2': b'b0b62e674f67306fddcf72fa888c3b56df100d64',
                          }, mapping)
