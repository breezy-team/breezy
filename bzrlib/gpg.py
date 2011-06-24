# Copyright (C) 2005, 2011 Canonical Ltd
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
    i18n,
    )
""")

#verification results
SIGNATURE_VALID = 0
SIGNATURE_KEY_MISSING = 1
SIGNATURE_NOT_VALID = 2
SIGNATURE_NOT_SIGNED = 3


class DisabledGPGStrategy(object):
    """A GPG Strategy that makes everything fail."""

    @staticmethod
    def verify_signatures_available():
        return True

    def __init__(self, ignored):
        """Real strategies take a configuration."""

    def sign(self, content):
        raise errors.SigningFailed('Signing is disabled.')

    def verify(self, content, testament):
        raise errors.SignatureVerificationFailed('Signature verification is \
disabled.')

    def set_acceptable_keys(self, command_line_input):
        pass


class LoopbackGPGStrategy(object):
    """A GPG Strategy that acts like 'cat' - data is just passed through."""

    @staticmethod
    def verify_signatures_available():
        return True

    def __init__(self, ignored):
        """Real strategies take a configuration."""

    def sign(self, content):
        return ("-----BEGIN PSEUDO-SIGNED CONTENT-----\n" + content +
                "-----END PSEUDO-SIGNED CONTENT-----\n")

    def verify(self, content, testament):
        return SIGNATURE_VALID, None

    def set_acceptable_keys(self, command_line_input):
        if command_line_input is not None:
            patterns = command_line_input.split(",")
            self.acceptable_keys = []
            for pattern in patterns:
                if pattern == "unknown":
                    pass
                else:
                    self.acceptable_keys.append(pattern)

    def do_verifications(self, revisions, repository):
        count = {SIGNATURE_VALID: 0,
                 SIGNATURE_KEY_MISSING: 0,
                 SIGNATURE_NOT_VALID: 0,
                 SIGNATURE_NOT_SIGNED: 0}
        result = []
        all_verifiable = True
        for rev_id in revisions:
            verification_result, uid =\
                                repository.verify_revision(rev_id,self)
            result.append([rev_id, verification_result, uid])
            count[verification_result] += 1
            if verification_result != SIGNATURE_VALID:
                all_verifiable = False
        return (count, result, all_verifiable)

    def valid_commits_message(self, count):
        return i18n.gettext("{0} commits with valid signatures").format(
                                        count[SIGNATURE_VALID])            

    def unknown_key_message(self, count):
        return i18n.ngettext("{0} commit with unknown key",
                             "{0} commits with unknown keys",
                             count[SIGNATURE_KEY_MISSING]).format(
                                        count[SIGNATURE_KEY_MISSING])

    def commit_not_valid_message(self, count):
        return i18n.ngettext("{0} commit not valid",
                             "{0} commits not valid",
                             count[SIGNATURE_NOT_VALID]).format(
                                            count[SIGNATURE_NOT_VALID])

    def commit_not_signed_message(self, count):
        return i18n.ngettext("{0} commit not signed",
                             "{0} commits not signed",
                             count[SIGNATURE_NOT_SIGNED]).format(
                                        count[SIGNATURE_NOT_SIGNED])


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

    acceptable_keys = None

    @staticmethod
    def verify_signatures_available():
        try:
            import gpgme
            return True
        except ImportError, error:
            return False

    def _command_line(self):
        return [self._config.gpg_signing_command(), '--clearsign']

    def __init__(self, config):
        self._config = config
        try:
            import gpgme
            self.context = gpgme.Context()
        except ImportError, error:
            pass # can't use verify()

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

    def verify(self, content, testament):
        """Check content has a valid signature.
        
        :param content: the commit signature
        :param testament: the valid testament string for the commit
        
        :return: SIGNATURE_VALID or a failed SIGNATURE_ value, key uid if valid
        """
        try:
            import gpgme
        except ImportError, error:
            raise errors.GpgmeNotInstalled(error)

        signature = StringIO(content)
        plain_output = StringIO()
        
        try:
            result = self.context.verify(signature, None, plain_output)
        except gpgme.GpgmeError,error:
            raise errors.SignatureVerificationFailed(error[2])

        if len(result) == 0:
            return SIGNATURE_NOT_VALID, None
        fingerprint = result[0].fpr
        if self.acceptable_keys is not None:
            if not fingerprint in self.acceptable_keys:
                return SIGNATURE_KEY_MISSING, fingerprint[-8:]
        if testament != plain_output.getvalue():
            return SIGNATURE_NOT_VALID, None
        if result[0].summary & gpgme.SIGSUM_VALID:
            key = self.context.get_key(fingerprint)
            name = key.uids[0].name
            email = key.uids[0].email
            return SIGNATURE_VALID, name + " <" + email + ">"
        if result[0].summary & gpgme.SIGSUM_RED:
            return SIGNATURE_NOT_VALID, None
        if result[0].summary & gpgme.SIGSUM_KEY_MISSING:
            return SIGNATURE_KEY_MISSING, fingerprint[-8:]
        #summary isn't set if sig is valid but key is untrusted
        if result[0].summary == 0 and self.acceptable_keys is not None:
            if fingerprint in self.acceptable_keys:
                return SIGNATURE_VALID, None
        else:
            return SIGNATURE_KEY_MISSING, None
        raise errors.SignatureVerificationFailed("Unknown GnuPG key "\
                                                 "verification result")

    def set_acceptable_keys(self, command_line_input):
        """sets the acceptable keys for verifying with this GPGStrategy
        
        :param command_line_input: comma separated list of patterns from
                                command line
        :return: nothing
        """
        key_patterns = None
        acceptable_keys_config = self._config.acceptable_keys()
        try:
            if isinstance(acceptable_keys_config, unicode):
                acceptable_keys_config = str(acceptable_keys_config)
        except UnicodeEncodeError:
            raise errors.BzrCommandError('Only ASCII permitted in option names')

        if acceptable_keys_config is not None:
            key_patterns = acceptable_keys_config
        if command_line_input is not None: #command line overrides config
            key_patterns = command_line_input
        if key_patterns is not None:
            patterns = key_patterns.split(",")

            self.acceptable_keys = []
            for pattern in patterns:
                result = self.context.keylist(pattern)
                found_key = False
                for key in result:
                    found_key = True
                    self.acceptable_keys.append(key.subkeys[0].fpr)
                    trace.mutter("Added acceptable key: " + key.subkeys[0].fpr)
                if not found_key:
                    trace.note(i18n.gettext(
                            "No GnuPG key results for pattern: {}"
                                ).format(pattern))

    def do_verifications(self, revisions, repository):
        """do verifications on a set of revisions
        
        :param revisions: list of revision ids to verify
        :param repository: repository object
        
        :return: count dictionary of results of each type,
                 result list for each revision,
                 boolean True if all results are verified successfully
        """
        count = {SIGNATURE_VALID: 0,
                 SIGNATURE_KEY_MISSING: 0,
                 SIGNATURE_NOT_VALID: 0,
                 SIGNATURE_NOT_SIGNED: 0}
        result = []
        all_verifiable = True
        for rev_id in revisions:
            verification_result, uid =\
                                repository.verify_revision(rev_id,self)
            result.append([rev_id, verification_result, uid])
            count[verification_result] += 1
            if verification_result != SIGNATURE_VALID:
                all_verifiable = False
        return (count, result, all_verifiable)

    def verbose_valid_message(self, result):
        """takes a verify result and returns list of signed commits strings"""
        signers = {}
        for rev_id, validity, uid in result:
            if validity == SIGNATURE_VALID:
                signers.setdefault(uid, 0)
                signers[uid] += 1
        result = []
        for uid, number in signers.items():
             result.append( i18n.ngettext("{0} signed {1} commit", 
                             "{0} signed {1} commits",
                             number).format(uid, number) )
        return result


    def verbose_not_valid_message(self, result, repo):
        """takes a verify result and returns list of not valid commit info"""
        signers = {}
        for rev_id, validity, empty in result:
            if validity == SIGNATURE_NOT_VALID:
                revision = repo.get_revision(rev_id)
                authors = ', '.join(revision.get_apparent_authors())
                signers.setdefault(authors, 0)
                signers[authors] += 1
        result = []
        for authors, number in signers.items():
            result.append( i18n.ngettext("{0} commit by author {1}", 
                                 "{0} commits by author {1}",
                                 number).format(number, authors) )
        return result

    def verbose_not_signed_message(self, result, repo):
        """takes a verify result and returns list of not signed commit info"""
        signers = {}
        for rev_id, validity, empty in result:
            if validity == SIGNATURE_NOT_SIGNED:
                revision = repo.get_revision(rev_id)
                authors = ', '.join(revision.get_apparent_authors())
                signers.setdefault(authors, 0)
                signers[authors] += 1
        result = []
        for authors, number in signers.items():
            result.append( i18n.ngettext("{0} commit by author {1}", 
                                 "{0} commits by author {1}",
                                 number).format(number, authors) )
        return result

    def verbose_missing_key_message(self, result):
        """takes a verify result and returns list of missing key info"""
        signers = {}
        for rev_id, validity, fingerprint in result:
            if validity == SIGNATURE_KEY_MISSING:
                signers.setdefault(fingerprint, 0)
                signers[fingerprint] += 1
        result = []
        for fingerprint, number in signers.items():
            result.append( i18n.ngettext("Unknown key {0} signed {1} commit", 
                                 "Unknown key {0} signed {1} commits",
                                 number).format(fingerprint, number) )
        return result

    def valid_commits_message(self, count):
        """returns message for number of commits"""
        return i18n.gettext("{0} commits with valid signatures").format(
                                        count[SIGNATURE_VALID])

    def unknown_key_message(self, count):
        """returns message for number of commits"""
        return i18n.ngettext("{0} commit with unknown key",
                             "{0} commits with unknown keys",
                             count[SIGNATURE_KEY_MISSING]).format(
                                        count[SIGNATURE_KEY_MISSING])

    def commit_not_valid_message(self, count):
        """returns message for number of commits"""
        return i18n.ngettext("{0} commit not valid",
                             "{0} commits not valid",
                             count[SIGNATURE_NOT_VALID]).format(
                                            count[SIGNATURE_NOT_VALID])

    def commit_not_signed_message(self, count):
        """returns message for number of commits"""
        return i18n.ngettext("{0} commit not signed",
                             "{0} commits not signed",
                             count[SIGNATURE_NOT_SIGNED]).format(
                                        count[SIGNATURE_NOT_SIGNED])
