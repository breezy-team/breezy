#!/usr/bin/env python
"""A test suite for the buildpackage plugin.
"""

import os
from bzrlib.selftest import TestCaseInTempDir
from bzrlib.branch import Branch

class TestBuildPackage(TestCaseInTempDir):
    def build_branches(self):
	self.build_tree(['foo',
			 'foo/bar'])
	a = Branch.initialize('foo')
	a.add('bar')
	a.working_tree().commit('foo', rev_id='foo-1')
	
    def test_buildpackage(self):
	self.run_bzr('buildpackage', 'foo', '0.1-1')

class TestRecordPackage(TestCaseInTempDir):
    def build_branches(self):
	self.build_tree(['foo',
			 'foo/bar'])
	a = Branch.initialize('foo')
	a.add('bar')
	a.working_tree().commit('foo', rev_id='foo-1')
	
    def test_recordpackage(self):
	self.run_bzr('recordpackage', 'foo', '0.1-1')
