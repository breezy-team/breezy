# Simple SVN pull / push functionality for bzr
# Copyright (C) 2005 Jelmer Vernooij <jelmer@samba.org>
# Published under the GNU GPL

"""
Support for foreign branches (Subversion)
"""
import sys
import os.path
import branch

sys.path.append(os.path.dirname(__file__))

try:
    from bzrlib.branch import register_branch_type
    register_branch_type(svnbranch.SvnBranch)
except ImportError:
    pass

def test_suite():
    from unittest import TestSuite, TestLoader
    import test_svnbranch

    suite = TestSuite()

    suite.addTest(TestLoader().loadTestsFromModule(test_svnbranch))

    return suite

