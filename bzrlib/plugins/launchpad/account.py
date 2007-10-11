from bzrlib import errors
from bzrlib.config import GlobalConfig
from bzrlib.transport import get_transport


LAUNCHPAD_BASE = 'https://launchpad.net/'


class UnknownLaunchpadUsername(errors.BzrError):
    _fmt = "The user name %(user)s is not registered on Launchpad."


class NoRegisteredSSHKeys(errors.BzrError):
    _fmt = "The user %(user)s has not registered any SSH keys with Launchpad."


def get_lp_username(config=None):
    """Return the user's Launchpad Username"""
    if config is None:
        config = GlobalConfig()

    return config.get_user_option('launchpad_username')


def set_lp_username(username, config=None):
    """Set the user's Launchpad username"""
    if config is None:
        config = GlobalConfig()

    config.set_user_option('launchpad_username', username)


def check_lp_username(username, transport=None):
    """Check whether the given Launchpad username is okay.

    This will check for both existance and whether the user has
    uploaded SSH keys.
    """

    if transport is None:
        transport = get_transport(LAUNCHPAD_BASE)

    try:
        data = transport.get_bytes('~%s/+sshkeys' % username)
    except errors.NoSuchFile:
        raise UnknownLaunchpadUsername(user=username)

    if not data:
        raise NoRegisteredSSHKeys(user=username)
