from bzrlib.branch import Branch

import pysvn

class SvnBranch(Branch):
    def __init__(self):
        self.client = pysvn.Client()
        self.client.set_auth_cache(True)
        
    def open(url):
        b = SvnBranch()
        return b
