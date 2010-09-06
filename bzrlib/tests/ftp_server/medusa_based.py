# Copyright (C) 2007-2010 Canonical Ltd
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
"""
FTP test server.

Based on medusa: http://www.amk.ca/python/code/medusa.html
"""

import asyncore
import errno
import os
import select
import stat
import threading

import medusa
import medusa.filesys
import medusa.ftp_server

from bzrlib import (
    tests,
    trace,
    )
from bzrlib.tests import test_server


class test_filesystem(medusa.filesys.os_filesystem):
    """A custom filesystem wrapper to add missing functionalities."""

    def chmod(self, path, mode):
        p = self.normalize(self.path_module.join (self.wd, path))
        return os.chmod(self.translate(p), mode)


class test_authorizer(object):
    """A custom Authorizer object for running the test suite.

    The reason we cannot use dummy_authorizer, is because it sets the
    channel to readonly, which we don't always want to do.
    """

    def __init__(self, root):
        self.root = root
        # If secured_user is set secured_password will be checked
        self.secured_user = None
        self.secured_password = None

    def authorize(self, channel, username, password):
        """Return (success, reply_string, filesystem)"""
        channel.persona = -1, -1
        if username == 'anonymous':
            channel.read_only = 1
        else:
            channel.read_only = 0

        # Check secured_user if set
        if (self.secured_user is not None
            and username == self.secured_user
            and password != self.secured_password):
            return 0, 'Password invalid.', None
        else:
            return 1, 'OK.', test_filesystem(self.root)


class ftp_channel(medusa.ftp_server.ftp_channel):
    """Customized ftp channel"""

    def log(self, message):
        """Redirect logging requests."""
        trace.mutter('ftp_channel: %s', message)

    def log_info(self, message, type='info'):
        """Redirect logging requests."""
        trace.mutter('ftp_channel %s: %s', type, message)

    def cmd_rnfr(self, line):
        """Prepare for renaming a file."""
        self._renaming = line[1]
        self.respond('350 Ready for RNTO')
        # TODO: jam 20060516 in testing, the ftp server seems to
        #       check that the file already exists, or it sends
        #       550 RNFR command failed

    def cmd_rnto(self, line):
        """Rename a file based on the target given.

        rnto must be called after calling rnfr.
        """
        if not self._renaming:
            self.respond('503 RNFR required first.')
        pfrom = self.filesystem.translate(self._renaming)
        self._renaming = None
        pto = self.filesystem.translate(line[1])
        if os.path.exists(pto):
            self.respond('550 RNTO failed: file exists')
            return
        try:
            os.rename(pfrom, pto)
        except (IOError, OSError), e:
            # TODO: jam 20060516 return custom responses based on
            #       why the command failed
            # (bialix 20070418) str(e) on Python 2.5 @ Windows
            # sometimes don't provide expected error message;
            # so we obtain such message via os.strerror()
            self.respond('550 RNTO failed: %s' % os.strerror(e.errno))
        except:
            self.respond('550 RNTO failed')
            # For a test server, we will go ahead and just die
            raise
        else:
            self.respond('250 Rename successful.')

    def cmd_size(self, line):
        """Return the size of a file

        This is overloaded to help the test suite determine if the
        target is a directory.
        """
        filename = line[1]
        if not self.filesystem.isfile(filename):
            if self.filesystem.isdir(filename):
                self.respond('550 "%s" is a directory' % (filename,))
            else:
                self.respond('550 "%s" is not a file' % (filename,))
        else:
            self.respond('213 %d'
                % (self.filesystem.stat(filename)[stat.ST_SIZE]),)

    def cmd_mkd(self, line):
        """Create a directory.

        Overloaded because default implementation does not distinguish
        *why* it cannot make a directory.
        """
        if len (line) != 2:
            self.command_not_understood(''.join(line))
        else:
            path = line[1]
            try:
                self.filesystem.mkdir (path)
                self.respond ('257 MKD command successful.')
            except (IOError, OSError), e:
                # (bialix 20070418) str(e) on Python 2.5 @ Windows
                # sometimes don't provide expected error message;
                # so we obtain such message via os.strerror()
                self.respond ('550 error creating directory: %s' %
                              os.strerror(e.errno))
            except:
                self.respond ('550 error creating directory.')

    def cmd_site(self, line):
        """Site specific commands."""
        command, args = line[1].split(' ', 1)
        if command.lower() == 'chmod':
            try:
                mode, path = args.split()
                mode = int(mode, 8)
            except ValueError:
                # We catch both malformed line and malformed mode with the same
                # ValueError.
                self.command_not_understood(' '.join(line))
                return
            try:
                # Yes path and mode are reversed
                self.filesystem.chmod(path, mode)
                self.respond('200 SITE CHMOD command successful')
            except AttributeError:
                # The chmod method is not available in read-only and will raise
                # AttributeError since a different filesystem is used in that
                # case
                self.command_not_authorized(' '.join(line))
        else:
            # Another site specific command was requested. We don't know that
            # one
            self.command_not_understood(' '.join(line))


class ftp_server(medusa.ftp_server.ftp_server):
    """Customize the behavior of the Medusa ftp_server.

    There are a few warts on the ftp_server, based on how it expects
    to be used.
    """
    _renaming = None
    ftp_channel_class = ftp_channel

    def __init__(self, *args, **kwargs):
        trace.mutter('Initializing ftp_server: %r, %r', args, kwargs)
        medusa.ftp_server.ftp_server.__init__(self, *args, **kwargs)

    def log(self, message):
        """Redirect logging requests."""
        trace.mutter('ftp_server: %s', message)

    def log_info(self, message, type='info'):
        """Override the asyncore.log_info so we don't stipple the screen."""
        trace.mutter('ftp_server %s: %s', type, message)


class FTPTestServer(test_server.TestServer):
    """Common code for FTP server facilities."""

    no_unicode_support = True

    def __init__(self):
        self._root = None
        self._ftp_server = None
        self._port = None
        self._async_thread = None
        # ftp server logs
        self.logs = []

    def get_url(self):
        """Calculate an ftp url to this server."""
        return 'ftp://foo:bar@localhost:%d/' % (self._port)

    def get_bogus_url(self):
        """Return a URL which cannot be connected to."""
        return 'ftp://127.0.0.1:1'

    def log(self, message):
        """This is used by medusa.ftp_server to log connections, etc."""
        self.logs.append(message)

    def start_server(self, vfs_server=None):
        if not (vfs_server is None or isinstance(vfs_server,
                                                 test_server.LocalURLServer)):
            raise AssertionError(
                "FTPServer currently assumes local transport, got %s" % vfs_server)
        self._root = os.getcwdu()
        self._ftp_server = ftp_server(
            authorizer=test_authorizer(root=self._root),
            ip='localhost',
            port=0, # bind to a random port
            resolver=None,
            logger_object=self # Use FTPServer.log() for messages
            )
        self._port = self._ftp_server.getsockname()[1]
        # Don't let it loop forever, or handle an infinite number of requests.
        # In this case it will run for 1000s, or 10000 requests
        self._async_thread = threading.Thread(
                target=FTPTestServer._asyncore_loop_ignore_EBADF,
                kwargs={'timeout':0.1, 'count':10000})
        if 'threads' in tests.selftest_debug_flags:
            sys.stderr.write('Thread started: %s\n'
                             % (self._async_thread.ident,))
        self._async_thread.setDaemon(True)
        self._async_thread.start()

    def stop_server(self):
        self._ftp_server.close()
        asyncore.close_all()
        self._async_thread.join()
        if 'threads' in tests.selftest_debug_flags:
            sys.stderr.write('Thread  joined: %s\n'
                             % (self._async_thread.ident,))

    @staticmethod
    def _asyncore_loop_ignore_EBADF(*args, **kwargs):
        """Ignore EBADF during server shutdown.

        We close the socket to get the server to shutdown, but this causes
        select.select() to raise EBADF.
        """
        try:
            asyncore.loop(*args, **kwargs)
            # FIXME: If we reach that point, we should raise an exception
            # explaining that the 'count' parameter in setUp is too low or
            # testers may wonder why their test just sits there waiting for a
            # server that is already dead. Note that if the tester waits too
            # long under pdb the server will also die.
        except select.error, e:
            if e.args[0] != errno.EBADF:
                raise

    def add_user(self, user, password):
        """Add a user with write access."""
        authorizer = server = self._ftp_server.authorizer
        authorizer.secured_user = user
        authorizer.secured_password = password

