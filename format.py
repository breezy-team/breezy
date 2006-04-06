from bzrlib.bzrdir import BzrDirFormat

class SvnFormat(BzrDirFormat):
    def _open(self, transport):
        print "Connected to %s" % transport

    def get_format_string(self):
        return 'SVN Repository'
