
# XXX: This import is for transitional purposes only.  This should go away ASAP.
from bzrlib.transport.smart._smart import *
from bzrlib.transport.smart.request import SmartServerRequestHandler

def get_test_permutations():
    """Return (transport, server) permutations for testing."""
    ### We may need a little more test framework support to construct an
    ### appropriate RemoteTransport in the future.
    from bzrlib.transport.smart import server
    return [(SmartTCPTransport, server.SmartTCPServer_for_testing)]
