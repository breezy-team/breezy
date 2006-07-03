# Copyright (C) 2006 by Canonical Ltd
# -*- coding: utf-8 -*-
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

"""Black-box tests for bzr handling non-ascii characters."""

import sys
import os

import bzrlib
import bzrlib.osutils as osutils
from bzrlib.tests import TestCaseWithTransport, TestSkipped
from bzrlib.trace import mutter, note
import bzrlib.urlutils as urlutils


class TestNonAscii(TestCaseWithTransport):
    """Test that bzr handles files/committers/etc which are non-ascii."""

    def setUp(self):
        super(TestNonAscii, self).setUp()
        self._orig_email = os.environ.get('BZREMAIL', None)
        self._orig_encoding = bzrlib.user_encoding

        bzrlib.user_encoding = self.encoding
        email = self.info['committer'] + ' <joe@foo.com>'
        os.environ['BZREMAIL'] = email.encode(bzrlib.user_encoding)
        self.create_base()

    def tearDown(self):
        if self._orig_email is not None:
            os.environ['BZREMAIL'] = self._orig_email
        else:
            if os.environ.get('BZREMAIL', None) is not None:
                del os.environ['BZREMAIL']
        bzrlib.user_encoding = self._orig_encoding
        super(TestNonAscii, self).tearDown()

    def create_base(self):
        bzr = self.run_bzr

        fs_enc = sys.getfilesystemencoding()
        terminal_enc = osutils.get_terminal_encoding()
        fname = self.info['filename']
        dir_name = self.info['directory']
        for thing in [fname, dir_name]:
            try:
                thing.encode(fs_enc)
            except UnicodeEncodeError:
                raise TestSkipped(('Unable to represent path %r'
                                   ' in filesystem encoding "%s"')
                                    % (thing, fs_enc))
            try:
                thing.encode(terminal_enc)
            except UnicodeEncodeError:
                raise TestSkipped(('Unable to represent path %r'
                                   ' in terminal encoding "%s"'
                                   ' (even though it is valid in'
                                   ' filesystem encoding "%s")')
                                   % (thing, terminal_enc, fs_enc))

        wt = self.make_branch_and_tree('.')
        open('a', 'wb').write('foo\n')
        wt.add('a')
        wt.commit('adding a')

        open('b', 'wb').write('non-ascii \xFF\xFF\xFC\xFB\x00 in b\n')
        wt.add('b')
        wt.commit(self.info['message'])

        open(fname, 'wb').write('unicode filename\n')
        wt.add(fname)
        wt.commit(u'And a unicode file\n')

    def test_status(self):
        bzr = self.run_bzr_decode

        open(self.info['filename'], 'ab').write('added something\n')
        txt = bzr('status')
        self.assertEqual(u'modified:\n  %s\n' % (self.info['filename'],), txt)

        txt = bzr('status', encoding='ascii')
        expected = u'modified:\n  %s\n' % (
                    self.info['filename'].encode('ascii', 'replace'),)
        self.assertEqual(expected, txt)

    def test_cat(self):
        # bzr cat shouldn't change the contents
        # using run_bzr since that doesn't decode
        txt = self.run_bzr('cat', 'b')[0]
        self.assertEqual('non-ascii \xFF\xFF\xFC\xFB\x00 in b\n', txt)

        txt = self.run_bzr('cat', self.info['filename'])[0]
        self.assertEqual('unicode filename\n', txt)

    def test_cat_revision(self):
        bzr = self.run_bzr_decode

        committer = self.info['committer']
        txt = bzr('cat-revision', '-r', '1')
        self.failUnless(committer in txt,
                        'failed to find %r in %r' % (committer, txt))

        msg = self.info['message']
        txt = bzr('cat-revision', '-r', '2')
        self.failUnless(msg in txt, 'failed to find %r in %r' % (msg, txt))

    def test_mkdir(self):
        bzr = self.run_bzr_decode

        txt = bzr('mkdir', self.info['directory'])
        self.assertEqual(u'added %s\n' % self.info['directory'], txt)

        # The text should be garbled, but the command should succeed
        txt = bzr('mkdir', self.info['directory'] + '2', encoding='ascii')
        expected = u'added %s2\n' % (self.info['directory'],)
        expected = expected.encode('ascii', 'replace')
        self.assertEqual(expected, txt)

    def test_relpath(self):
        bzr = self.run_bzr_decode

        txt = bzr('relpath', self.info['filename'])
        self.assertEqual(self.info['filename'] + '\n', txt)

        bzr('relpath', self.info['filename'], encoding='ascii', retcode=3)

    def test_inventory(self):
        bzr = self.run_bzr_decode

        txt = bzr('inventory')
        self.assertEqual(['a', 'b', self.info['filename']],
                         txt.splitlines())

        # inventory should fail if unable to encode
        bzr('inventory', encoding='ascii', retcode=3)

        # We don't really care about the ids themselves,
        # but the command shouldn't fail
        txt = bzr('inventory', '--show-ids')

    def test_revno(self):
        # There isn't a lot to test here, since revno should always
        # be an integer
        bzr = self.run_bzr_decode

        self.assertEqual('3\n', bzr('revno'))
        self.assertEqual('3\n', bzr('revno', encoding='ascii'))

    def test_revision_info(self):
        bzr = self.run_bzr_decode

        bzr('revision-info', '-r', '1')

        # TODO: jam 20060105 If we support revisions with non-ascii characters,
        # this should be strict and fail.
        bzr('revision-info', '-r', '1', encoding='ascii')

    def test_mv(self):
        bzr = self.run_bzr_decode

        fname1 = self.info['filename']
        fname2 = self.info['filename'] + '2'
        dirname = self.info['directory']

        # fname1 already exists
        bzr('mv', 'a', fname1, retcode=3)

        txt = bzr('mv', 'a', fname2)
        self.assertEqual(u'a => %s\n' % fname2, txt)
        self.failIfExists('a')
        self.failUnlessExists(fname2)

        bzr('commit', '-m', 'renamed to non-ascii')

        bzr('mkdir', dirname)
        txt = bzr('mv', fname1, fname2, dirname)
        self.assertEqual([u'%s => %s/%s' % (fname1, dirname, fname1),
                          u'%s => %s/%s' % (fname2, dirname, fname2)]
                         , txt.splitlines())

        # The rename should still succeed
        newpath = u'%s/%s' % (dirname, fname2)
        txt = bzr('mv', newpath, 'a', encoding='ascii')
        self.failUnlessExists('a')
        self.assertEqual(newpath.encode('ascii', 'replace') + ' => a\n', txt)

    def test_branch(self):
        # We should be able to branch into a directory that
        # has a unicode name, even if we can't display the name
        bzr = self.run_bzr_decode
        bzr('branch', u'.', self.info['directory'])
        bzr('branch', u'.', self.info['directory'] + '2', encoding='ascii')

    def test_pull(self):
        # Make sure we can pull from paths that can't be encoded
        bzr = self.run_bzr_decode

        dirname1 = self.info['directory']
        dirname2 = self.info['directory'] + '2'
        bzr('branch', '.', dirname1)
        bzr('branch', dirname1, dirname2)

        os.chdir(dirname1)
        open('a', 'ab').write('more text\n')
        bzr('commit', '-m', 'mod a')

        pwd = osutils.getcwd()

        os.chdir(u'../' + dirname2)
        txt = bzr('pull')

        self.assertEqual(u'Using saved location: %s/\n' % (pwd,), txt)

        os.chdir('../' + dirname1)
        open('a', 'ab').write('and yet more\n')
        bzr('commit', '-m', 'modifying a by ' + self.info['committer'])

        os.chdir('../' + dirname2)
        # We should be able to pull, even if our encoding is bad
        bzr('pull', '--verbose', encoding='ascii')

    def test_push(self):
        # TODO: Test push to an SFTP location
        # Make sure we can pull from paths that can't be encoded
        bzr = self.run_bzr_decode

        # TODO: jam 20060427 For drastically improving performance, we probably
        #       could create a local repository, so it wouldn't have to copy
        #       the files around as much.

        dirname = self.info['directory']
        bzr('push', dirname)

        open('a', 'ab').write('adding more text\n')
        bzr('commit', '-m', 'added some stuff')

        # TODO: check the output text is properly encoded
        bzr('push')

        f = open('a', 'ab')
        f.write('and a bit more: ')
        f.write(dirname.encode('utf-8'))
        f.write('\n')
        f.close()

        bzr('commit', '-m', u'Added some ' + dirname)
        bzr('push', '--verbose', encoding='ascii')

        bzr('push', '--verbose', dirname + '2')

        bzr('push', '--verbose', dirname + '3', encoding='ascii')

        bzr('push', '--verbose', '--create-prefix', dirname + '4/' + dirname + '5')
        bzr('push', '--verbose', '--create-prefix', dirname + '6/' + dirname + '7', encoding='ascii')

    def test_renames(self):
        bzr = self.run_bzr_decode

        fname = self.info['filename'] + '2'
        bzr('mv', 'a', fname)
        txt = bzr('renames')
        self.assertEqual(u'a => %s\n' % fname, txt)

        bzr('renames', retcode=3, encoding='ascii')

    def test_remove(self):
        bzr = self.run_bzr_decode

        fname = self.info['filename']
        txt = bzr('remove', fname, encoding='ascii')

    def test_remove_verbose(self):
        bzr = self.run_bzr_decode

        fname = self.info['filename']
        txt = bzr('remove', '--verbose', fname, encoding='ascii')

    def test_file_id(self):
        bzr = self.run_bzr_decode

        fname = self.info['filename']
        txt = bzr('file-id', fname)

        # TODO: jam 20060106 We don't support non-ascii file ids yet, 
        #       so there is nothing which would fail in ascii encoding
        #       This *should* be retcode=3
        txt = bzr('file-id', fname, encoding='ascii')

    def test_file_path(self):
        bzr = self.run_bzr_decode

        # Create a directory structure
        fname = self.info['filename']
        dirname = self.info['directory']
        bzr('mkdir', 'base')
        bzr('mkdir', 'base/' + dirname)
        path = '/'.join(['base', dirname, fname])
        bzr('mv', fname, path)
        bzr('commit', '-m', 'moving things around')

        txt = bzr('file-path', path)

        # TODO: jam 20060106 We don't support non-ascii file ids yet, 
        #       so there is nothing which would fail in ascii encoding
        #       This *should* be retcode=3
        txt = bzr('file-path', path, encoding='ascii')

    def test_revision_history(self):
        bzr = self.run_bzr_decode

        # TODO: jam 20060106 We don't support non-ascii revision ids yet, 
        #       so there is nothing which would fail in ascii encoding
        txt = bzr('revision-history')

    def test_ancestry(self):
        bzr = self.run_bzr_decode

        # TODO: jam 20060106 We don't support non-ascii revision ids yet, 
        #       so there is nothing which would fail in ascii encoding
        txt = bzr('ancestry')

    def test_diff(self):
        # TODO: jam 20060106 diff is a difficult one to test, because it 
        #       shouldn't encode the file contents, but it needs some sort
        #       of encoding for the paths, etc which are displayed.
        open(self.info['filename'], 'ab').write('newline\n')
        txt = self.run_bzr('diff', retcode=1)[0]

    def test_deleted(self):
        bzr = self.run_bzr_decode

        fname = self.info['filename']
        os.remove(fname)
        bzr('rm', fname)

        txt = bzr('deleted')
        self.assertEqual(fname+'\n', txt)

        txt = bzr('deleted', '--show-ids')
        self.failUnless(txt.startswith(fname))

        # Deleted should fail if cannot decode
        # Because it is giving the exact paths
        # which might be used by a front end
        bzr('deleted', encoding='ascii', retcode=3)

    def test_modified(self):
        bzr = self.run_bzr_decode

        fname = self.info['filename']
        open(fname, 'ab').write('modified\n')

        txt = bzr('modified')
        self.assertEqual(fname+'\n', txt)

        bzr('modified', encoding='ascii', retcode=3)

    def test_added(self):
        bzr = self.run_bzr_decode

        fname = self.info['filename'] + '2'
        open(fname, 'wb').write('added\n')
        bzr('add', fname)

        txt = bzr('added')
        self.assertEqual(fname+'\n', txt)

        bzr('added', encoding='ascii', retcode=3)

    def test_root(self):
        bzr = self.run_bzr_decode

        dirname = self.info['directory']
        bzr('root')

        bzr('branch', u'.', dirname)

        os.chdir(dirname)

        txt = bzr('root')
        self.failUnless(txt.endswith(dirname+'\n'))

        txt = bzr('root', encoding='ascii', retcode=3)

    def test_log(self):
        bzr = self.run_bzr_decode

        fname = self.info['filename']

        txt = bzr('log')
        self.assertNotEqual(-1, txt.find(self.info['committer']))
        self.assertNotEqual(-1, txt.find(self.info['message']))

        txt = bzr('log', '--verbose')
        self.assertNotEqual(-1, txt.find(fname))

        # Make sure log doesn't fail even if we can't write out
        txt = bzr('log', '--verbose', encoding='ascii')
        self.assertEqual(-1, txt.find(fname))
        self.assertNotEqual(-1, txt.find(fname.encode('ascii', 'replace')))

    def test_touching_revisions(self):
        bzr = self.run_bzr_decode

        fname = self.info['filename']
        txt = bzr('touching-revisions', fname)
        self.assertEqual(u'     3 added %s\n' % (fname,), txt)

        fname2 = self.info['filename'] + '2'
        bzr('mv', fname, fname2)
        bzr('commit', '-m', u'Renamed %s => %s' % (fname, fname2))

        txt = bzr('touching-revisions', fname2)
        expected_txt = (u'     3 added %s\n' 
                        u'     4 renamed %s => %s\n'
                        % (fname, fname, fname2))
        self.assertEqual(expected_txt, txt)

        bzr('touching-revisions', fname2, encoding='ascii', retcode=3)

    def test_ls(self):
        bzr = self.run_bzr_decode

        txt = bzr('ls')
        self.assertEqual(['a', 'b', self.info['filename']],
                         txt.splitlines())
        txt = bzr('ls', '--null')
        self.assertEqual(['a', 'b', self.info['filename'], ''],
                         txt.split('\0'))

        txt = bzr('ls', encoding='ascii', retcode=3)
        txt = bzr('ls', '--null', encoding='ascii', retcode=3)

    def test_unknowns(self):
        bzr = self.run_bzr_decode

        fname = self.info['filename'] + '2'
        open(fname, 'wb').write('unknown\n')

        # TODO: jam 20060112 bzr unknowns is the only one which 
        #       quotes paths do we really want it to?
        txt = bzr('unknowns')
        self.assertEqual(u'"%s"\n' % (fname,), txt)

        bzr('unknowns', encoding='ascii', retcode=3)

    def test_ignore(self):
        bzr = self.run_bzr_decode

        fname2 = self.info['filename'] + '2.txt'
        open(fname2, 'wb').write('ignored\n')

        txt = bzr('unknowns')
        self.assertEqual(u'"%s"\n' % (fname2,), txt)

        bzr('ignore', './' + fname2)
        txt = bzr('unknowns')
        self.assertEqual(u'', txt)

        fname3 = self.info['filename'] + '3.txt'
        open(fname3, 'wb').write('unknown 3\n')
        txt = bzr('unknowns')
        self.assertEqual(u'"%s"\n' % (fname3,), txt)

        # Ignore should not care what the encoding is
        # (right now it doesn't print anything)
        bzr('ignore', fname3, encoding='ascii')
        txt = bzr('unknowns')
        self.assertEqual('', txt)

        # Now try a wildcard match
        fname4 = self.info['filename'] + '4.txt'
        open(fname4, 'wb').write('unknown 4\n')
        bzr('ignore', '*.txt')
        txt = bzr('unknowns')
        self.assertEqual('', txt)

        os.remove('.bzrignore')
        bzr('ignore', self.info['filename'] + '*')
        txt = bzr('unknowns')
        self.assertEqual('', txt)

    def test_missing(self):
        bzr = self.run_bzr_decode

        # create empty tree as reference for missing
        self.run_bzr('init', 'empty-tree')

        msg = self.info['message']

        txt = bzr('missing', 'empty-tree', retcode=1)
        self.assertNotEqual(-1, txt.find(self.info['committer']))
        self.assertNotEqual(-1, txt.find(msg))

        # Make sure missing doesn't fail even if we can't write out
        txt = bzr('missing', 'empty-tree', encoding='ascii', retcode=1)
        self.assertEqual(-1, txt.find(msg))
        self.assertNotEqual(-1, txt.find(msg.encode('ascii', 'replace')))
