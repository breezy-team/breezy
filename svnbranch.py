from bzrlib.branch import Branch
from bzrlib.errors import NotBranchError

import pysvn

class SvnBranch(Branch):
    """
    Branch representing a subversion branch
    """
    def __init__(self, client):
        self.client = client
        self.client.set_auth_cache(True)

    def _uuid():
        """ Return UUID of the SVN repository """
        #FIXME
        raise NotImplementedError

    @staticmethod
    def open_containing(base):
        client = pysvn.Client()

        if not client.is_url(base):
            raise NotBranchError
        
        b = SvnBranch(client)
        #FIXME
        raise NotBranchError
        return b
        
    @staticmethod
    def open(url):
        client = pysvn.Client()

        if not client.is_url(url):
            raise NotBranchError

        b = SvnBranch(client)
        raise NotBranchError
        #FIXME
        return b

    # Functions that don't make sense for SvnBranch:
    def get_revision_xml(self, revision_id):
        raise NotImplementedError

    def get_inventory_xml(self, revision_id):
        raise NotImplementedError
    
    def pending_merges(self):
        raise NotImplementedError

    def put_controlfile(self, path, f, encode=True):
        raise NotImplementedError

    def put_controlfiles(self, files, encode=True):
        raise NotImplementedError

    def pullable_revisions(self, other, stop_revision):
        raise NotImplementedError

    def missing_revisions(self, other, stop_revision=None, diverged_ok=False):
        raise NotImplementedError

    def controlfilename(self, file_or_path):
        raise NotImplementedError

    def check_revno(self, revno):
        #FIXME
        raise NotImplementedError

    def revno(self):
        #FIXME
        raise NotImplementedError

    def print_file(self, file, revno):
        #FIXME
        raise NotImplementedError

    def has_revision(self):
        #FIXME
        raise NotImplementedError

    def get_transaction(self):
        #FIXME
        raise NotImplementedError

    def get_inventory(self):
        #FIXME
        raise NotImplementedError

    def get_parent(self):
        #FIXME
        raise NotImplementedError

    def revision_history():
        # FIXME: Get list of revisions
        raise NotImplementedError

    def get_ancestry():
        #FIXME
        raise NotImplementedError

    def last_revision():
        #FIXME
        raise NotImplementedError
