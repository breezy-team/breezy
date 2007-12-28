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

"""Test our ability to build up test repositories"""

from cStringIO import StringIO

from bzrlib.plugins.git import tests


class TestGitBranchBuilder(tests.TestCase):

    def test__create_blob(self):
        stream = StringIO()
        builder = tests.GitBranchBuilder(stream)
        self.assertEqual(1, builder._create_blob('foo\nbar\n'))
        self.assertEqualDiff('blob\nmark :1\ndata 8\nfoo\nbar\n\n',
                             stream.getvalue())

    def test_set_file(self):
        stream = StringIO()
        builder = tests.GitBranchBuilder(stream)
        builder.set_file('foobar', 'foo\nbar\n', False)
        self.assertEqualDiff('blob\nmark :1\ndata 8\nfoo\nbar\n\n',
                             stream.getvalue())
        self.assertEqual(['M 100644 :1 foobar\n'], builder.commit_info)

    def test_set_file_unicode(self):
        stream = StringIO()
        builder = tests.GitBranchBuilder(stream)
        builder.set_file(u'f\xb5/bar', 'contents\nbar\n', False)
        self.assertEqualDiff('blob\nmark :1\ndata 13\ncontents\nbar\n\n',
                             stream.getvalue())
        self.assertEqual(['M 100644 :1 f\xc2\xb5/bar\n'], builder.commit_info)

    def test_set_file_executable(self):
        stream = StringIO()
        builder = tests.GitBranchBuilder(stream)
        builder.set_file(u'f\xb5/bar', 'contents\nbar\n', True)
        self.assertEqualDiff('blob\nmark :1\ndata 13\ncontents\nbar\n\n',
                             stream.getvalue())
        self.assertEqual(['M 100755 :1 f\xc2\xb5/bar\n'], builder.commit_info)

    def test_set_link(self):
        stream = StringIO()
        builder = tests.GitBranchBuilder(stream)
        builder.set_link(u'f\xb5/bar', 'link/contents')
        self.assertEqualDiff('blob\nmark :1\ndata 13\nlink/contents\n',
                             stream.getvalue())
        self.assertEqual(['M 120000 :1 f\xc2\xb5/bar\n'], builder.commit_info)

    def test_delete_entry(self):
        stream = StringIO()
        builder = tests.GitBranchBuilder(stream)
        builder.delete_entry(u'path/to/f\xb5')
        self.assertEqual(['D path/to/f\xc2\xb5\n'], builder.commit_info)

    def test_add_and_commit(self):
        stream = StringIO()
        builder = tests.GitBranchBuilder(stream)

        builder.set_file(u'f\xb5/bar', 'contents\nbar\n', False)
        self.assertEqual(2, builder.commit('Joe Foo <joe@foo.com>',
                                           u'committing f\xb5/bar',
                                           timestamp=1194586400,
                                           timezone='+0100'))
        self.assertEqualDiff('blob\nmark :1\ndata 13\ncontents\nbar\n\n'
                             'commit refs/heads/master\n'
                             'mark :2\n'
                             'committer Joe Foo <joe@foo.com> 1194586400 +0100\n'
                             'data 18\n'
                             'committing f\xc2\xb5/bar'
                             '\n'
                             'M 100644 :1 f\xc2\xb5/bar\n'
                             '\n',
                             stream.getvalue())

    def test_commit_base(self):
        stream = StringIO()
        builder = tests.GitBranchBuilder(stream)

        builder.set_file(u'foo', 'contents\nfoo\n', False)
        r1 = builder.commit('Joe Foo <joe@foo.com>', u'first',
                            timestamp=1194586400)
        r2 = builder.commit('Joe Foo <joe@foo.com>', u'second',
                            timestamp=1194586405)
        r3 = builder.commit('Joe Foo <joe@foo.com>', u'third',
                            timestamp=1194586410,
                            base=r1)

        self.assertEqualDiff('blob\nmark :1\ndata 13\ncontents\nfoo\n\n'
                             'commit refs/heads/master\n'
                             'mark :2\n'
                             'committer Joe Foo <joe@foo.com> 1194586400 +0000\n'
                             'data 5\n'
                             'first'
                             '\n'
                             'M 100644 :1 foo\n'
                             '\n'
                             'commit refs/heads/master\n'
                             'mark :3\n'
                             'committer Joe Foo <joe@foo.com> 1194586405 +0000\n'
                             'data 6\n'
                             'second'
                             '\n'
                             '\n'
                             'commit refs/heads/master\n'
                             'mark :4\n'
                             'committer Joe Foo <joe@foo.com> 1194586410 +0000\n'
                             'data 5\n'
                             'third'
                             '\n'
                             'from :2\n'
                             '\n', stream.getvalue())

    def test_commit_merge(self):
        stream = StringIO()
        builder = tests.GitBranchBuilder(stream)

        builder.set_file(u'foo', 'contents\nfoo\n', False)
        r1 = builder.commit('Joe Foo <joe@foo.com>', u'first',
                            timestamp=1194586400)
        r2 = builder.commit('Joe Foo <joe@foo.com>', u'second',
                            timestamp=1194586405)
        r3 = builder.commit('Joe Foo <joe@foo.com>', u'third',
                            timestamp=1194586410,
                            base=r1)
        r4 = builder.commit('Joe Foo <joe@foo.com>', u'Merge',
                            timestamp=1194586415,
                            merge=[r2])

        self.assertEqualDiff('blob\nmark :1\ndata 13\ncontents\nfoo\n\n'
                             'commit refs/heads/master\n'
                             'mark :2\n'
                             'committer Joe Foo <joe@foo.com> 1194586400 +0000\n'
                             'data 5\n'
                             'first'
                             '\n'
                             'M 100644 :1 foo\n'
                             '\n'
                             'commit refs/heads/master\n'
                             'mark :3\n'
                             'committer Joe Foo <joe@foo.com> 1194586405 +0000\n'
                             'data 6\n'
                             'second'
                             '\n'
                             '\n'
                             'commit refs/heads/master\n'
                             'mark :4\n'
                             'committer Joe Foo <joe@foo.com> 1194586410 +0000\n'
                             'data 5\n'
                             'third'
                             '\n'
                             'from :2\n'
                             '\n'
                             'commit refs/heads/master\n'
                             'mark :5\n'
                             'committer Joe Foo <joe@foo.com> 1194586415 +0000\n'
                             'data 5\n'
                             'Merge'
                             '\n'
                             'merge :3\n'
                             '\n', stream.getvalue())

    def test_auto_timestamp(self):
        stream = StringIO()
        builder = tests.GitBranchBuilder(stream)
        builder.commit('Joe Foo <joe@foo.com>', u'message')
        self.assertContainsRe(stream.getvalue(),
                              r'committer Joe Foo <joe@foo\.com> \d+ \+0000')


class TestGitBranchBuilderReal(tests.TestCaseInTempDir):

    def test_create_real_branch(self):
        tests.run_git('init')

        builder = tests.GitBranchBuilder()
        builder.set_file(u'foo', 'contents\nfoo\n', False)
        r1 = builder.commit('Joe Foo <joe@foo.com>', u'first',
                            timestamp=1194586400)
        mapping = builder.finish()
        self.assertEqual({1:'44411e8e9202177dd19b6599d7a7991059fa3cb4',
                          2: 'b0b62e674f67306fddcf72fa888c3b56df100d64',
                         }, mapping)
