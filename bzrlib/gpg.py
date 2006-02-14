# Copyright (C) 2005 by Canonical Ltd
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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""GPG signing and checking logic."""

import errno
import subprocess
import tempfile

import bzrlib.errors as errors


class DisabledGPGStrategy(object):
    """A GPG Strategy that makes everything fail."""

    def __init__(self, ignored):
        """Real strategies take a configuration."""

    def sign(self, content):
        raise errors.SigningFailed('Signing is disabled.')


class LoopbackGPGStrategy(object):
    """A GPG Strategy that acts like 'cat' - data is just passed through."""

    def __init__(self, ignored):
        """Real strategies take a configuration."""

    def sign(self, content):
        return content


class GPGStrategy(object):
    """GPG Signing and checking facilities."""
        
    def _command_line(self):
        return [self._config.gpg_signing_command(),
                '--output', '-', '--clearsign']

    def __init__(self, config):
        self._config = config

    def sign(self, content):
        f = tempfile.NamedTemporaryFile()
        cmd = self._command_line() + [f.name]
        f.write(content)
        f.flush()
        try:
            process = subprocess.Popen(cmd,
                                       stdout=subprocess.PIPE)
            try:
                result = process.communicate()[0]
                if process.returncode is None:
                    process.wait()
                if process.returncode != 0:
                    raise errors.SigningFailed(cmd)
                return result
            except OSError, e:
                if e.errno == errno.EPIPE:
                    raise errors.SigningFailed(cmd)
                else:
                    raise
        except ValueError:
            # bad subprocess parameters, should never happen.
            raise
        except OSError, e:
            if e.errno == errno.ENOENT:
                # gpg is not installed
                raise errors.SigningFailed(cmd)
            else:
                raise
        f.close()
