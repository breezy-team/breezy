# Copyright (C) 2005 Canonical Ltd
#   Authors: Robert Collins <robert.collins@canonical.com>
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

"""GPG signing and checking logic."""

import os
import sys
from StringIO import StringIO

from bzrlib.lazy_import import lazy_import
lazy_import(globals(), """
import errno
import subprocess

from bzrlib import (
    errors,
    trace,
    ui,
    )
""")

#verification results
SIGNATURE_VALID = 0
SIGNATURE_KEY_MISSING = 1
SIGNATURE_NOT_VALID = 2
SIGNATURE_NOT_SIGNED = 3


class DisabledGPGStrategy(object):
    """A GPG Strategy that makes everything fail."""

    def __init__(self, ignored):
        """Real strategies take a configuration."""

    def sign(self, content):
        raise errors.SigningFailed('Signing is disabled.')

    def verification(self, content):
        raise errors.VerifyFailed('Signature verification is disabled.')


class LoopbackGPGStrategy(object):
    """A GPG Strategy that acts like 'cat' - data is just passed through."""

    def __init__(self, ignored):
        """Real strategies take a configuration."""

    def sign(self, content):
        return ("-----BEGIN PSEUDO-SIGNED CONTENT-----\n" + content +
                "-----END PSEUDO-SIGNED CONTENT-----\n")

    def verification(self, content):
        return SIGNATURE_VALID


def _set_gpg_tty():
    tty = os.environ.get('TTY')
    if tty is not None:
        os.environ['GPG_TTY'] = tty
        trace.mutter('setting GPG_TTY=%s', tty)
    else:
        # This is not quite worthy of a warning, because some people
        # don't need GPG_TTY to be set. But it is worthy of a big mark
        # in ~/.bzr.log, so that people can debug it if it happens to them
        trace.mutter('** Env var TTY empty, cannot set GPG_TTY.'
                     '  Is TTY exported?')


class GPGStrategy(object):
    """GPG Signing and checking facilities."""

    def _command_line(self):
        return [self._config.gpg_signing_command(), '--clearsign']

    def __init__(self, config):
        self._config = config

    def sign(self, content):
        if isinstance(content, unicode):
            raise errors.BzrBadParameterUnicode('content')
        ui.ui_factory.clear_term()

        preexec_fn = _set_gpg_tty
        if sys.platform == 'win32':
            # Win32 doesn't support preexec_fn, but wouldn't support TTY anyway.
            preexec_fn = None
        try:
            process = subprocess.Popen(self._command_line(),
                                       stdin=subprocess.PIPE,
                                       stdout=subprocess.PIPE,
                                       preexec_fn=preexec_fn)
            try:
                result = process.communicate(content)[0]
                if process.returncode is None:
                    process.wait()
                if process.returncode != 0:
                    raise errors.SigningFailed(self._command_line())
                return result
            except OSError, e:
                if e.errno == errno.EPIPE:
                    raise errors.SigningFailed(self._command_line())
                else:
                    raise
        except ValueError:
            # bad subprocess parameters, should never happen.
            raise
        except OSError, e:
            if e.errno == errno.ENOENT:
                # gpg is not installed
                raise errors.SigningFailed(self._command_line())
            else:
                raise

    def verify(self, content):
        """Check content has a valid signature.
        
        :param content: the commit signature
        
        :return: SIGNATURE_VALID or a failed SIGNATURE_ value
        """
        try:
            import gpgme
        except ImportError:
            raise errors.GpgmeNotInstalled()

        context = gpgme.Context()
        signature = StringIO(content)
        plain_output = StringIO()
        
        try:
            result = context.verify(signature, None, plain_output)
        except gpgme.GpgmeError,error:
            raise errors.VerifyFailed(error[2])

        if result[0].summary & gpgme.SIGSUM_VALID:
            return SIGNATURE_VALID
        if result[0].summary & gpgme.SIGSUM_RED:
            return SIGNATURE_NOT_VALID
        if result[0].summary & gpgme.SIGSUM_KEY_MISSING:
            return SIGNATURE_NOT_VALID
