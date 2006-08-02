#!/usr/bin/python2.4

import os
import sys
import shutil
import re

from bzrlib.commands import Command, register_command
from bzrlib.option import Option
from bzrlib.errors import (NoSuchFile, NotBranchError, BzrNewError)
from bzrlib.branch import Branch
from bzrlib.workingtree import WorkingTree
from bzrlib.export import export

class DebianError(BzrNewError):
  """A Debian packaging error occured: %(message)s"""

  def __init__(self, message):
    BzrNewError.__init__(self)
    self.message = message

class cmd_buildpackage(Command):
  """Build the package
  """
  dry_run_opt = Option('dry-run', help="don't do anything")
  Option.SHORT_OPTIONS['n'] = dry_run_opt
  working_tree_opt = Option('working-tree', help="Use the wokring tree")
  Option.SHORT_OPTIONS['w'] = working_tree_opt
  export_only_opt = Option('export-only', help="Export only, don't build")
  Option.SHORT_OPTIONS['e'] = export_only_opt
  dont_purge_opt = Option('dont-purge', help="Don't purge the build directory after building")
  takes_args = ['branch?', 'version?']
  takes_options = ['verbose',
           dry_run_opt, working_tree_opt, export_only_opt, dont_purge_opt]

  def run(self, branch=None, version=None, verbose=False, working_tree=False, export_only=False, dont_purge=False):
    retcode = 0

    if branch is None:
      tree = WorkingTree.open_containing('.')[0]
    else:
      tree = WorkingTree.open_containing(branch)[0]

    if not working_tree:
      b = tree.branch
      rev_id = b.last_revision()
      t = b.repository.revision_tree(rev_id)
    else:
      t = tree
    if not version:
      if not t.has_filename('debian/changelog'):
        raise DebianError("Could not open debian/changelog")
      changelog_id = t.inventory.path2id('debian/changelog')
      changelog = t.get_file_text(changelog_id)
      p = re.compile('([a-z0-9][-a-z0-9.+]+) \(([-0-9a-z.:]+)\) [-a-zA-Z]+; urgency=[a-z]+')
      m = p.search(changelog)
      if m is not None:
        package = m.group(1)
        version = m.group(2)
    
    if version is None:
      raise DebianError("Could not parse debian/changelog")

    p = re.compile('(.+)-[^-]+')
    m = p.match(version)
    if m is not None:
      upstream = m.group(1)
    else:
      upstream = version

    dir = package + "-" + upstream

    if branch is None:
      os.chdir('..')

    if not os.path.exists('build-area'):
      os.mkdir('build-area')
    os.chdir('build-area')
    if os.path.exists(dir): 
      shutil.rmtree(dir)
    export(t,dir,None,None)
    if not export_only:
      os.chdir(dir)
      os.system('dpkg-buildpackage -uc -us -rfakeroot')
      os.chdir('..')
      if not dont_purge:
        shutil.rmtree(dir)

    return retcode

class cmd_recordpackage(Command):
  """Record the package
  """
  dry_run_opt = Option('dry-run', help="don't do anything")
  Option.SHORT_OPTIONS['n'] = dry_run_opt
  takes_args = ['package', 'version?']
  takes_options = ['verbose',
           dry_run_opt]

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
register_command(cmd_recordpackage)
