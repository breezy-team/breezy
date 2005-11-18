#!/usr/bin/env python

import os
import sys

from bzrlib.commands import Command, register_command
from bzrlib.errors import (NoSuchFile, NotBranchError)
from bzrlib.branch import Branch

class cmd_buildpackage(Command):
	"""Build the package
	"""
	takes_args = ['package', 'version?']
	takes_options = ['verbose']

	def run(self, package, version=None, verbose=False):
		retcode = 0

		return retcode

def test_suite():
	from unittest import TestSuite, TestLoader
	import test_buildpackage
	suite = TestSuite()
	suite.addTest(TestLoader().loadTestsFromModule(test_buildpackage))
	return suite

register_command(cmd_buildpackage)
