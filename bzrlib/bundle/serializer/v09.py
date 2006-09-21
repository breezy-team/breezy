from bzrlib.bundle.serializer import BUNDLE_HEADER
from bzrlib.bundle.serializer.v08 import BundleSerializerV08

class BundleSerializerV09(BundleSerializerV08):

    def check_compatible(self):
        pass

    def _write_main_header(self):
        """Write the header for the changes"""
        f = self.to_file
        f.write(BUNDLE_HEADER)
        f.write('0.9\n')
        f.write('#\n')

