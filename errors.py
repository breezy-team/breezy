
from bzrlib.errors import BzrNewError


class DebianError(BzrNewError):
  """A Debian packaging error occured: %(message)s"""

  def __init__(self, message):
    BzrNewError.__init__(self)
    self.message = message

class ChangedError(DebianError):
  """There are modified files in the working tree. Either commit the 
  changes, use --working to build the working tree, or --ignore-changes
  to override this and build the branch without the changes in the working 
  tree. Use bzr status to see the changes"""

  def __init__(self):
    DebianError.__init__(self, None)

class NoSourceDirError(DebianError):
  """There is no existing source directory to use. Use --export-only or 
  --dont-purge to get one that can be used"""

  def __init__(self):
    DebianError.__init__(self, None)

class NotInBaseError(BzrNewError):
  """Must be invoked from the base of a branch."""
  def __init__(self):
    BzrNewError.__init__(self)

