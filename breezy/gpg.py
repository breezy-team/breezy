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

import os

from breezy.lazy_import import lazy_import
lazy_import(globals(), """
from breezy import (
    config,
    trace,
    ui,
    )
from breezy.i18n import (
    gettext,
    ngettext,
    )
""")

from . import (
    errors,
    )

# verification results
SIGNATURE_VALID = 0
SIGNATURE_KEY_MISSING = 1
SIGNATURE_NOT_VALID = 2
SIGNATURE_NOT_SIGNED = 3
SIGNATURE_EXPIRED = 4

MODE_NORMAL = 0
MODE_DETACH = 1
MODE_CLEAR = 2


class GpgNotInstalled(errors.DependencyNotPresent):

    _fmt = ('python-gpg is not installed, it is needed to create or '
            'verify signatures. %(error)s')

    def __init__(self, error):
        errors.DependencyNotPresent.__init__(self, 'gpg', error)


class SigningFailed(errors.BzrError):

    _fmt = 'Failed to GPG sign data: "%(error)s"'

    def __init__(self, error):
        errors.BzrError.__init__(self, error=error)


class SignatureVerificationFailed(errors.BzrError):

    _fmt = 'Failed to verify GPG signature data with error "%(error)s"'

    def __init__(self, error):
        errors.BzrError.__init__(self, error=error)


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
    with ui.ui_factory.nested_progress_bar() as pb:
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
    return (count, result, all_verifiable)


class DisabledGPGStrategy(object):
    """A GPG Strategy that makes everything fail."""

    @staticmethod
    def verify_signatures_available():
        return True

    def __init__(self, ignored):
        """Real strategies take a configuration."""

    def sign(self, content, mode):
        raise SigningFailed('Signing is disabled.')

    def verify(self, signed_data, signature=None):
        raise SignatureVerificationFailed('Signature verification is \
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

    def sign(self, content, mode):
        return (b"-----BEGIN PSEUDO-SIGNED CONTENT-----\n" + content
                + b"-----END PSEUDO-SIGNED CONTENT-----\n")

    def verify(self, signed_data, signature=None):
        plain_text = signed_data.replace(
            b"-----BEGIN PSEUDO-SIGNED CONTENT-----\n", b"")
        plain_text = plain_text.replace(
            b"-----END PSEUDO-SIGNED CONTENT-----\n", b"")
        return SIGNATURE_VALID, None, plain_text

    def set_acceptable_keys(self, command_line_input):
        if command_line_input is not None:
            patterns = command_line_input.split(",")
            self.acceptable_keys = []
            for pattern in patterns:
                if pattern == "unknown":
                    pass
                else:
                    self.acceptable_keys.append(pattern)


def _set_gpg_tty():
    tty = os.environ.get('TTY')
    if tty is not None:
        os.environ['GPG_TTY'] = tty
        trace.mutter('setting GPG_TTY=%s', tty)
    else:
        # This is not quite worthy of a warning, because some people
        # don't need GPG_TTY to be set. But it is worthy of a big mark
        # in brz.log, so that people can debug it if it happens to them
        trace.mutter('** Env var TTY empty, cannot set GPG_TTY.'
                     '  Is TTY exported?')


class GPGStrategy(object):
    """GPG Signing and checking facilities."""

    acceptable_keys = None

    def __init__(self, config_stack):
        self._config_stack = config_stack
        try:
            import gpg
            self.context = gpg.Context()
            self.context.armor = True
            self.context.signers = self._get_signing_keys()
        except ModuleNotFoundError:
            pass  # can't use verify()

    def _get_signing_keys(self):
        import gpg
        keyname = self._config_stack.get('gpg_signing_key')
        if keyname == 'default':
            # Leave things to gpg
            return []

        if keyname:
            try:
                return [self.context.get_key(keyname)]
            except gpg.errors.KeyNotFound:
                pass

        if keyname is None:
            # not setting gpg_signing_key at all means we should
            # use the user email address
            keyname = config.extract_email_address(
                self._config_stack.get('email'))
        if keyname == 'default':
            return []
        possible_keys = self.context.keylist(keyname, secret=True)
        try:
            return [next(possible_keys)]
        except StopIteration:
            return []

    @staticmethod
    def verify_signatures_available():
        """
        check if this strategy can verify signatures

        :return: boolean if this strategy can verify signatures
        """
        try:
            import gpg  # noqa: F401
            return True
        except ModuleNotFoundError:
            return False

    def sign(self, content, mode):
        try:
            import gpg
        except ModuleNotFoundError as error:
            raise GpgNotInstalled(
                'Set create_signatures=no to disable creating signatures.')

        if isinstance(content, str):
            raise errors.BzrBadParameterUnicode('content')

        plain_text = gpg.Data(content)
        try:
            output, result = self.context.sign(
                plain_text, mode={
                    MODE_DETACH: gpg.constants.sig.mode.DETACH,
                    MODE_CLEAR: gpg.constants.sig.mode.CLEAR,
                    MODE_NORMAL: gpg.constants.sig.mode.NORMAL,
                    }[mode])
        except gpg.errors.GPGMEError as error:
            raise SigningFailed(str(error))
        except gpg.errors.InvalidSigners as error:
            raise SigningFailed(str(error))

        return output

    def verify(self, signed_data, signature=None):
        """Check content has a valid signature.

        :param signed_data; Signed data
        :param signature: optional signature (if detached)

        :return: SIGNATURE_VALID or a failed SIGNATURE_ value, key uid if valid, plain text
        """
        try:
            import gpg
        except ModuleNotFoundError as error:
            raise GpgNotInstalled(
                'Set check_signatures=ignore to disable verifying signatures.')

        signed_data = gpg.Data(signed_data)
        if signature:
            signature = gpg.Data(signature)
        try:
            plain_output, result = self.context.verify(signed_data, signature)
        except gpg.errors.BadSignatures as error:
            fingerprint = error.result.signatures[0].fpr
            if error.result.signatures[0].summary & gpg.constants.SIGSUM_KEY_EXPIRED:
                expires = self.context.get_key(
                    error.result.signatures[0].fpr).subkeys[0].expires
                if expires > error.result.signatures[0].timestamp:
                    # The expired key was not expired at time of signing.
                    # test_verify_expired_but_valid()
                    return SIGNATURE_EXPIRED, fingerprint[-8:], None
                else:
                    # I can't work out how to create a test where the signature
                    # was expired at the time of signing.
                    return SIGNATURE_NOT_VALID, None, None

            # GPG does not know this key.
            # test_verify_unknown_key()
            if (error.result.signatures[0].summary &
                    gpg.constants.SIGSUM_KEY_MISSING):
                return SIGNATURE_KEY_MISSING, fingerprint[-8:], None

            return SIGNATURE_NOT_VALID, None, None
        except gpg.errors.GPGMEError as error:
            raise SignatureVerificationFailed(error)

        # No result if input is invalid.
        # test_verify_invalid()
        if len(result.signatures) == 0:
            return SIGNATURE_NOT_VALID, None, plain_output

        # User has specified a list of acceptable keys, check our result is in
        # it.  test_verify_unacceptable_key()
        fingerprint = result.signatures[0].fpr
        if self.acceptable_keys is not None:
            if fingerprint not in self.acceptable_keys:
                return SIGNATURE_KEY_MISSING, fingerprint[-8:], plain_output
        # Yay gpg set the valid bit.
        # Can't write a test for this one as you can't set a key to be
        # trusted using gpg.
        if result.signatures[0].summary & gpg.constants.SIGSUM_VALID:
            key = self.context.get_key(fingerprint)
            name = key.uids[0].name
            if isinstance(name, bytes):
                name = name.decode('utf-8')
            email = key.uids[0].email
            if isinstance(email, bytes):
                email = email.decode('utf-8')
            return (SIGNATURE_VALID, name + u" <" + email + u">", plain_output)
        # Sigsum_red indicates a problem, unfortunatly I have not been able
        # to write any tests which actually set this.
        if result.signatures[0].summary & gpg.constants.SIGSUM_RED:
            return SIGNATURE_NOT_VALID, None, plain_output
        # Summary isn't set if sig is valid but key is untrusted but if user
        # has explicity set the key as acceptable we can validate it.
        if (result.signatures[0].summary == 0 and
                self.acceptable_keys is not None):
            if fingerprint in self.acceptable_keys:
                # test_verify_untrusted_but_accepted()
                return SIGNATURE_VALID, None, plain_output
        # test_verify_valid_but_untrusted()
        if result.signatures[0].summary == 0 and self.acceptable_keys is None:
            return SIGNATURE_NOT_VALID, None, plain_output
        # Other error types such as revoked keys should (I think) be caught by
        # SIGSUM_RED so anything else means something is buggy.
        raise SignatureVerificationFailed(
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
        if command_line_input is not None:  # command line overrides config
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
    for fingerprint, number in list(signers.items()):
        result.append(ngettext(u"Unknown key {0} signed {1} commit",
                               u"Unknown key {0} signed {1} commits",
                               number).format(fingerprint, number))
    return result
