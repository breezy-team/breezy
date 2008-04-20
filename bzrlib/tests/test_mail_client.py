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
    mail_client,
    tests,
    urlutils,
    )

class TestMutt(tests.TestCase):

    def test_commandline(self):
        mutt = mail_client.Mutt(None)
        commandline = mutt._get_compose_commandline(None, None, 'file%')
        self.assertEqual(['-a', 'file%'], commandline)
        commandline = mutt._get_compose_commandline('jrandom@example.org',
                                                     'Hi there!', None)
        self.assertEqual(['-s', 'Hi there!', 'jrandom@example.org'],
                         commandline)

    def test_commandline_is_8bit(self):
        mutt = mail_client.Mutt(None)
        cmdline = mutt._get_compose_commandline(u'jrandom@example.org',
            u'Hi there!', u'file%')
        self.assertEqual(
            ['-s', 'Hi there!', '-a', 'file%', 'jrandom@example.org'],
            cmdline)
        for item in cmdline:
            self.assertFalse(isinstance(item, unicode),
                'Command-line item %r is unicode!' % item)


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

    def test_commandline_is_8bit(self):
        # test for bug #139318
        tbird = mail_client.Thunderbird(None)
        cmdline = tbird._get_compose_commandline(u'jrandom@example.org',
            u'Hi there!', u'file%')
        self.assertEqual(['-compose',
            ("attachment='%s'," % urlutils.local_path_to_url('file%')) +
            "subject='Hi there!',to='jrandom@example.org'",
            ], cmdline)
        for item in cmdline:
            self.assertFalse(isinstance(item, unicode),
                'Command-line item %r is unicode!' % item)


class TestEmacsMail(tests.TestCase):

    def test_commandline(self):
        eclient = mail_client.EmacsMail(None)

        commandline = eclient._get_compose_commandline(None, 'Hi there!', None)
        self.assertEqual(['--eval', '(compose-mail nil "Hi there!")'],
                         commandline)

        commandline = eclient._get_compose_commandline('jrandom@example.org',
                                                       'Hi there!', None)
        self.assertEqual(['--eval',
                          '(compose-mail "jrandom@example.org" "Hi there!")'],
                         commandline)

        # We won't be able to know the temporary file name at this stage
        # so we can't raise an assertion with assertEqual
        cmdline = eclient._get_compose_commandline(None, None, 'file%')
        commandline = ' '.join(cmdline)
        self.assertContainsRe(commandline, '--eval')
        self.assertContainsRe(commandline, '(compose-mail nil nil)')
        self.assertContainsRe(commandline, '(load .*)')
        self.assertContainsRe(commandline, '(bzr-add-mime-att \"file%\")')

    def test_commandline_is_8bit(self):
        eclient = mail_client.EmacsMail(None)
        commandline = eclient._get_compose_commandline(u'jrandom@example.org',
            u'Hi there!', u'file%')
        for item in commandline:
            self.assertFalse(isinstance(item, unicode),
                'Command-line item %r is unicode!' % item)


class TestXDGEmail(tests.TestCase):

    def test_commandline(self):
        xdg_email = mail_client.XDGEmail(None)
        self.assertRaises(errors.NoMailAddressSpecified,
                          xdg_email._get_compose_commandline,
                          None, None, 'file%')
        commandline = xdg_email._get_compose_commandline(
            'jrandom@example.org', None, 'file%')
        self.assertEqual(['jrandom@example.org', '--attach', 'file%'],
                         commandline)
        commandline = xdg_email._get_compose_commandline(
            'jrandom@example.org', 'Hi there!', None)
        self.assertEqual(['jrandom@example.org', '--subject', 'Hi there!'],
                         commandline)

    def test_commandline_is_8bit(self):
        xdg_email = mail_client.XDGEmail(None)
        cmdline = xdg_email._get_compose_commandline(u'jrandom@example.org',
            u'Hi there!', u'file%')
        self.assertEqual(
            ['jrandom@example.org', '--subject', 'Hi there!',
             '--attach', 'file%'],
            cmdline)
        for item in cmdline:
            self.assertFalse(isinstance(item, unicode),
                'Command-line item %r is unicode!' % item)


class TestEvolution(tests.TestCase):

    def test_commandline(self):
        evo = mail_client.Evolution(None)
        commandline = evo._get_compose_commandline(None, None, 'file%')
        self.assertEqual(['mailto:?attach=file%25'], commandline)
        commandline = evo._get_compose_commandline('jrandom@example.org',
                                                   'Hi there!', None)
        self.assertEqual(['mailto:jrandom@example.org?subject=Hi%20there%21'],
                         commandline)

    def test_commandline_is_8bit(self):
        evo = mail_client.Evolution(None)
        cmdline = evo._get_compose_commandline(u'jrandom@example.org',
            u'Hi there!', u'file%')
        self.assertEqual(
            ['mailto:jrandom@example.org?attach=file%25&subject=Hi%20there%21'
            ],
            cmdline)
        for item in cmdline:
            self.assertFalse(isinstance(item, unicode),
                'Command-line item %r is unicode!' % item)


class TestKMail(tests.TestCase):

    def test_commandline(self):
        kmail = mail_client.KMail(None)
        commandline = kmail._get_compose_commandline(None, None, 'file%')
        self.assertEqual(['--attach', 'file%'], commandline)
        commandline = kmail._get_compose_commandline('jrandom@example.org',
                                                     'Hi there!', None)
        self.assertEqual(['-s', 'Hi there!', 'jrandom@example.org'],
                         commandline)

    def test_commandline_is_8bit(self):
        kmail = mail_client.KMail(None)
        cmdline = kmail._get_compose_commandline(u'jrandom@example.org',
            u'Hi there!', u'file%')
        self.assertEqual(
            ['-s', 'Hi there!', '--attach', 'file%', 'jrandom@example.org'],
            cmdline)
        for item in cmdline:
            self.assertFalse(isinstance(item, unicode),
                'Command-line item %r is unicode!' % item)


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


class DummyMailClient(object):

    def compose_merge_request(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs


class DefaultMailDummyClient(mail_client.DefaultMail):

    def __init__(self):
        self.client = DummyMailClient()

    def _mail_client(self):
        return self.client


class TestDefaultMail(tests.TestCase):

    def test_compose_merge_request(self):
        client = DefaultMailDummyClient()
        to = "a@b.com"
        subject = "[MERGE]"
        directive = "directive",
        basename = "merge"
        client.compose_merge_request(to, subject, directive,
                                     basename=basename)
        dummy_client = client.client
        self.assertEqual(dummy_client.args, (to, subject, directive))
        self.assertEqual(dummy_client.kwargs, {"basename":basename})
