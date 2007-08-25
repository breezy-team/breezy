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
    mail_client,
    tests,
    urlutils,
    )


class TestThunderbird(tests.TestCase):

    def test_commandline(self):
        tbird = mail_client.Thunderbird(None)
        commandline = tbird._get_compose_commandline(None, None,
                                                     'file%')
        self.assertEqual(['-compose', "attachment='%s'" %
                          urlutils.local_path_to_url('file%')], commandline)
        commandline = tbird._get_compose_commandline('jrandom@example.org',
                                                     'Hi there!', None)
        self.assertEqual(['-compose', "subject='Hi there!',"
                                      "to='jrandom@example.org'"], commandline)


class TestXDGEmail(tests.TestCase):

    def test_commandline(self):
        xdg_email = mail_client.XDGEmail(None)
        commandline = xdg_email._get_compose_commandline(None, None,
                                                         'file%')
        self.assertEqual([None, '--attach', 'file%'], commandline)
        commandline = xdg_email._get_compose_commandline(
            'jrandom@example.org', 'Hi there!', None)
        self.assertEqual(['jrandom@example.org', '--subject', 'Hi there!'],
                         commandline)


class TestEvolution(tests.TestCase):

    def test_commandline(self):
        evo = mail_client.Evolution(None)
        commandline = evo._get_compose_commandline(None, None, 'file%')
        self.assertEqual(['mailto:?attach=file%25'], commandline)
        commandline = evo._get_compose_commandline('jrandom@example.org',
                                                   'Hi there!', None)
        self.assertEqual(['mailto:jrandom@example.org?subject=Hi%20there%21'],
                         commandline)


class TestKMail(tests.TestCase):

    def test_commandline(self):
        kmail = mail_client.KMail(None)
        commandline = kmail._get_compose_commandline(None, None, 'file%')
        self.assertEqual(['--attach', 'file%'], commandline)
        commandline = kmail._get_compose_commandline('jrandom@example.org',
                                                     'Hi there!', None)
        self.assertEqual(['-s', 'Hi there!', 'jrandom@example.org'],
                         commandline)


class TestEditor(tests.TestCase):

    def test_get_merge_prompt_unicode(self):
        """Prompt, to and subject are unicode, the attachement is binary"""
        editor = mail_client.Editor(None)
        prompt = editor._get_merge_prompt(u'foo\u1234',
                                        u'bar\u1234',
                                        u'baz\u1234',
                                        u'qux\u1234'.encode('utf-8'))
        self.assertContainsRe(prompt, u'foo\u1234(.|\n)*bar\u1234'
                              u'(.|\n)*baz\u1234(.|\n)*qux\u1234')
        editor._get_merge_prompt(u'foo', u'bar', u'baz', 'qux\xff')
