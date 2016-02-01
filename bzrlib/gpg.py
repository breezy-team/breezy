# Copyright (C) 2005, 2006, 2007, 2009, 2011, 2012, 2013, 2016 Canonical Ltd
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

from __future__ import absolute_import

import os
import sys
from StringIO import StringIO

from bzrlib.lazy_import import lazy_import
lazy_import(globals(), """
import errno
import subprocess

from bzrlib import (
    config,
    errors,
    trace,
    ui,
    )
from bzrlib.i18n import (
    gettext, 
    ngettext,
    )
""")

from bzrlib.symbol_versioning import (
    deprecated_in,
    deprecated_method,
    )

#verification results
SIGNATURE_VALID = 0
SIGNATURE_KEY_MISSING = 1
SIGNATURE_NOT_VALID = 2
SIGNATURE_NOT_SIGNED = 3
SIGNATURE_EXPIRED = 4


def bulk_verify_signatures(repository, revids, strategy,
        process_events_callback=None):
    """Do verifications on a set of revisions

    :param repository: repository object
    :param revids: list of revision ids to verify
    :param strategy: GPG strategy to use
    :param process_events_callback: method to call for GUI frontends that
        want to keep their UI refreshed

    :return: count dictionary of results of each type,
             result list for each revision,
             boolean True if all results are verified successfully
    """
    count = {SIGNATURE_VALID: 0,
             SIGNATURE_KEY_MISSING: 0,
             SIGNATURE_NOT_VALID: 0,
             SIGNATURE_NOT_SIGNED: 0,
             SIGNATURE_EXPIRED: 0}
    result = []
    all_verifiable = True
    total = len(revids)
    pb = ui.ui_factory.nested_progress_bar()
    try:
        for i, (rev_id, verification_result, uid) in enumerate(
                repository.verify_revision_signatures(
                    revids, strategy)):
            pb.update("verifying signatures", i, total)
            result.append([rev_id, verification_result, uid])
            count[verification_result] += 1
            if verification_result != SIGNATURE_VALID:
                all_verifiable = False
            if process_events_callback is not None:
                process_events_callback()
    finally:
        pb.finished()
    return (count, result, all_verifiable)


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
    """A GPG Strategy that acts like 'cat' - data is just passed through.
    Used in tests.
    """

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

    @deprecated_method(deprecated_in((2, 6, 0)))
    def do_verifications(self, revisions, repository):
        return bulk_verify_signatures(repository, revisions, self)

    @deprecated_method(deprecated_in((2, 6, 0)))
    def valid_commits_message(self, count):
        return valid_commits_message(count)

    @deprecated_method(deprecated_in((2, 6, 0)))
    def unknown_key_message(self, count):
        return unknown_key_message(count)

    @deprecated_method(deprecated_in((2, 6, 0)))
    def commit_not_valid_message(self, count):
        return commit_not_valid_message(count)

    @deprecated_method(deprecated_in((2, 6, 0)))
    def commit_not_signed_message(self, count):
        return commit_not_signed_message(count)

    @deprecated_method(deprecated_in((2, 6, 0)))
    def expired_commit_message(self, count):
        return expired_commit_message(count)


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

    def __init__(self, config_stack):
        self._config_stack = config_stack
        try:
            import gpgme
            self.context = gpgme.Context()
        except ImportError, error:
            pass # can't use verify()

    @staticmethod
    def verify_signatures_available():
        """
        check if this strategy can verify signatures

        :return: boolean if this strategy can verify signatures
        """
        try:
            import gpgme
            return True
        except ImportError, error:
            return False

    def _command_line(self):
        key = self._config_stack.get('gpg_signing_key')
        if key is None or key == 'default':
            # 'default' or not setting gpg_signing_key at all means we should
            # use the user email address
            key = config.extract_email_address(self._config_stack.get('email'))
        return [self._config_stack.get('gpg_signing_command'), '--clearsign',
                '-u', key]

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

        # No result if input is invalid.
        # test_verify_invalid()
        if len(result) == 0:
            return SIGNATURE_NOT_VALID, None
        # User has specified a list of acceptable keys, check our result is in
        # it.  test_verify_unacceptable_key()
        fingerprint = result[0].fpr
        if self.acceptable_keys is not None:
            if not fingerprint in self.acceptable_keys:
                return SIGNATURE_KEY_MISSING, fingerprint[-8:]
        # Check the signature actually matches the testament.
        # test_verify_bad_testament()
        if testament != plain_output.getvalue():
            return SIGNATURE_NOT_VALID, None
        # Yay gpgme set the valid bit.
        # Can't write a test for this one as you can't set a key to be
        # trusted using gpgme.
        if result[0].summary & gpgme.SIGSUM_VALID:
            key = self.context.get_key(fingerprint)
            name = key.uids[0].name
            email = key.uids[0].email
            return SIGNATURE_VALID, name + " <" + email + ">"
        # Sigsum_red indicates a problem, unfortunatly I have not been able
        # to write any tests which actually set this.
        if result[0].summary & gpgme.SIGSUM_RED:
            return SIGNATURE_NOT_VALID, None
        # GPG does not know this key.
        # test_verify_unknown_key()
        if result[0].summary & gpgme.SIGSUM_KEY_MISSING:
            return SIGNATURE_KEY_MISSING, fingerprint[-8:]
        # Summary isn't set if sig is valid but key is untrusted but if user
        # has explicity set the key as acceptable we can validate it.
        if result[0].summary == 0 and self.acceptable_keys is not None:
            if fingerprint in self.acceptable_keys:
                # test_verify_untrusted_but_accepted()
                return SIGNATURE_VALID, None
        # test_verify_valid_but_untrusted()
        if result[0].summary == 0 and self.acceptable_keys is None:
            return SIGNATURE_NOT_VALID, None
        if result[0].summary & gpgme.SIGSUM_KEY_EXPIRED:
            expires = self.context.get_key(result[0].fpr).subkeys[0].expires
            if expires > result[0].timestamp:
                # The expired key was not expired at time of signing.
                # test_verify_expired_but_valid()
                return SIGNATURE_EXPIRED, fingerprint[-8:]
            else:
                # I can't work out how to create a test where the signature
                # was expired at the time of signing.
                return SIGNATURE_NOT_VALID, None
        # A signature from a revoked key gets this.
        # test_verify_revoked_signature()
        if ((result[0].summary & gpgme.SIGSUM_SYS_ERROR
             or result[0].status.strerror == 'Certificate revoked')):
            return SIGNATURE_NOT_VALID, None
        # Other error types such as revoked keys should (I think) be caught by
        # SIGSUM_RED so anything else means something is buggy.
        raise errors.SignatureVerificationFailed(
            "Unknown GnuPG key verification result")

    def set_acceptable_keys(self, command_line_input):
        """Set the acceptable keys for verifying with this GPGStrategy.

        :param command_line_input: comma separated list of patterns from
                                command line
        :return: nothing
        """
        patterns = None
        acceptable_keys_config = self._config_stack.get('acceptable_keys')
        if acceptable_keys_config is not None:
            patterns = acceptable_keys_config
        if command_line_input is not None: # command line overrides config
            patterns = command_line_input.split(',')

        if patterns:
            self.acceptable_keys = []
            for pattern in patterns:
                result = self.context.keylist(pattern)
                found_key = False
                for key in result:
                    found_key = True
                    self.acceptable_keys.append(key.subkeys[0].fpr)
                    trace.mutter("Added acceptable key: " + key.subkeys[0].fpr)
                if not found_key:
                    trace.note(gettext(
                            "No GnuPG key results for pattern: {0}"
                                ).format(pattern))

    @deprecated_method(deprecated_in((2, 6, 0)))
    def do_verifications(self, revisions, repository,
                            process_events_callback=None):
        """do verifications on a set of revisions

        :param revisions: list of revision ids to verify
        :param repository: repository object
        :param process_events_callback: method to call for GUI frontends that
            want to keep their UI refreshed

        :return: count dictionary of results of each type,
                 result list for each revision,
                 boolean True if all results are verified successfully
        """
        return bulk_verify_signatures(repository, revisions, self,
            process_events_callback)

    @deprecated_method(deprecated_in((2, 6, 0)))
    def verbose_valid_message(self, result):
        """takes a verify result and returns list of signed commits strings"""
        return verbose_valid_message(result)

    @deprecated_method(deprecated_in((2, 6, 0)))
    def verbose_not_valid_message(self, result, repo):
        """takes a verify result and returns list of not valid commit info"""
        return verbose_not_valid_message(result, repo)

    @deprecated_method(deprecated_in((2, 6, 0)))
    def verbose_not_signed_message(self, result, repo):
        """takes a verify result and returns list of not signed commit info"""
        return verbose_not_valid_message(result, repo)

    @deprecated_method(deprecated_in((2, 6, 0)))
    def verbose_missing_key_message(self, result):
        """takes a verify result and returns list of missing key info"""
        return verbose_missing_key_message(result)

    @deprecated_method(deprecated_in((2, 6, 0)))
    def verbose_expired_key_message(self, result, repo):
        """takes a verify result and returns list of expired key info"""
        return verbose_expired_key_message(result, repo)

    @deprecated_method(deprecated_in((2, 6, 0)))
    def valid_commits_message(self, count):
        """returns message for number of commits"""
        return valid_commits_message(count)

    @deprecated_method(deprecated_in((2, 6, 0)))
    def unknown_key_message(self, count):
        """returns message for number of commits"""
        return unknown_key_message(count)

    @deprecated_method(deprecated_in((2, 6, 0)))
    def commit_not_valid_message(self, count):
        """returns message for number of commits"""
        return commit_not_valid_message(count)

    @deprecated_method(deprecated_in((2, 6, 0)))
    def commit_not_signed_message(self, count):
        """returns message for number of commits"""
        return commit_not_signed_message(count)

    @deprecated_method(deprecated_in((2, 6, 0)))
    def expired_commit_message(self, count):
        """returns message for number of commits"""
        return expired_commit_message(count)


def valid_commits_message(count):
    """returns message for number of commits"""
    return gettext(u"{0} commits with valid signatures").format(
                                    count[SIGNATURE_VALID])


def unknown_key_message(count):
    """returns message for number of commits"""
    return ngettext(u"{0} commit with unknown key",
                    u"{0} commits with unknown keys",
                    count[SIGNATURE_KEY_MISSING]).format(
                                    count[SIGNATURE_KEY_MISSING])


def commit_not_valid_message(count):
    """returns message for number of commits"""
    return ngettext(u"{0} commit not valid",
                    u"{0} commits not valid",
                    count[SIGNATURE_NOT_VALID]).format(
                                        count[SIGNATURE_NOT_VALID])


def commit_not_signed_message(count):
    """returns message for number of commits"""
    return ngettext(u"{0} commit not signed",
                    u"{0} commits not signed",
                    count[SIGNATURE_NOT_SIGNED]).format(
                                    count[SIGNATURE_NOT_SIGNED])


def expired_commit_message(count):
    """returns message for number of commits"""
    return ngettext(u"{0} commit with key now expired",
                    u"{0} commits with key now expired",
                    count[SIGNATURE_EXPIRED]).format(
                                count[SIGNATURE_EXPIRED])


def verbose_expired_key_message(result, repo):
    """takes a verify result and returns list of expired key info"""
    signers = {}
    fingerprint_to_authors = {}
    for rev_id, validity, fingerprint in result:
        if validity == SIGNATURE_EXPIRED:
            revision = repo.get_revision(rev_id)
            authors = ', '.join(revision.get_apparent_authors())
            signers.setdefault(fingerprint, 0)
            signers[fingerprint] += 1
            fingerprint_to_authors[fingerprint] = authors
    result = []
    for fingerprint, number in signers.items():
        result.append(
            ngettext(u"{0} commit by author {1} with key {2} now expired",
                     u"{0} commits by author {1} with key {2} now expired",
                     number).format(
                number, fingerprint_to_authors[fingerprint], fingerprint))
    return result


def verbose_valid_message(result):
    """takes a verify result and returns list of signed commits strings"""
    signers = {}
    for rev_id, validity, uid in result:
        if validity == SIGNATURE_VALID:
            signers.setdefault(uid, 0)
            signers[uid] += 1
    result = []
    for uid, number in signers.items():
         result.append(ngettext(u"{0} signed {1} commit",
                                u"{0} signed {1} commits",
                                number).format(uid, number))
    return result


def verbose_not_valid_message(result, repo):
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
        result.append(ngettext(u"{0} commit by author {1}",
                               u"{0} commits by author {1}",
                               number).format(number, authors))
    return result


def verbose_not_signed_message(result, repo):
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
        result.append(ngettext(u"{0} commit by author {1}",
                               u"{0} commits by author {1}",
                               number).format(number, authors))
    return result


def verbose_missing_key_message(result):
    """takes a verify result and returns list of missing key info"""
    signers = {}
    for rev_id, validity, fingerprint in result:
        if validity == SIGNATURE_KEY_MISSING:
            signers.setdefault(fingerprint, 0)
            signers[fingerprint] += 1
    result = []
    for fingerprint, number in signers.items():
        result.append(ngettext(u"Unknown key {0} signed {1} commit",
                               u"Unknown key {0} signed {1} commits",
                               number).format(fingerprint, number))
    return result
