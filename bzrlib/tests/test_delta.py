# Copyright (C) 2007 Canonical Ltd
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

from bzrlib import (
    delta,
    inventory,
    tests,
    )


class InstrumentedReporter(object):
    def __init__(self):
        self.calls = []

    def report(self, file_id, path, versioned, renamed, modified, exe_change,
               kind):
        self.calls.append((file_id, path, versioned, renamed, modified,
                           exe_change, kind))


class TestReportChanges(tests.TestCase):
    """Test the new change reporting infrastructure"""

    def assertReport(self, expected, file_id='fid', path='path',
                     versioned_change='unchanged', renamed=False,
                     modified='unchanged', exe_change=False,
                     kind=('file', 'file'), old_path=None):
        result = []
        def result_line(format, *args):
            result.append(format % args)
        inv = inventory.Inventory()
        if old_path is not None:
            inv.add(inventory.InventoryFile(file_id, old_path,
                                            inv.root.file_id))
        reporter = delta.ChangeReporter(inv, result_line)
        reporter.report(file_id, path, versioned_change, renamed, modified,
                         exe_change, kind)
        self.assertEqualDiff(expected, result[0])

    def test_rename(self):
        self.assertReport('R   old => path', renamed=True, old_path='old')
        self.assertReport('    path')

    def test_kind(self):
        self.assertReport(' K  path => path/', modified='kind changed',
                          kind=('file', 'directory'))
        self.assertReport(' K  path/ => path', modified='kind changed',
                          kind=('directory', 'file'), old_path='old')
        self.assertReport('RK  old => path/', renamed=True,
                          modified='kind changed', 
                          kind=('file', 'directory'), old_path='old')
    def test_new(self):
        self.assertReport(' N  path/', modified='created',
                          kind=(None, 'directory'))
        self.assertReport('+   path/', versioned_change='added',
                          modified='unchanged', kind=(None, 'directory'))
        self.assertReport('+N  path/', versioned_change='added',
                          modified='created', kind=(None, 'directory'))
        self.assertReport('+M  path/', versioned_change='added',
                          modified='modified', kind=(None, 'directory'))
        self.assertReport('+K  path => path/', versioned_change='added',
                          modified='kind changed', kind=('file', 'directory'))

    def test_removal(self):
        self.assertReport(' D  path/', modified='deleted',
                          kind=('directory', None), old_path='old')
        self.assertReport('-   path/', versioned_change='removed',
                          kind=(None, 'directory'))
        self.assertReport('-D  path', versioned_change='removed',
                          modified='deleted', kind=('file', 'directory'))

    def test_modification(self):
        self.assertReport(' M  path', modified='modified')
        self.assertReport(' M* path', modified='modified', exe_change=True)

    def assertChangesEqual(self,
                           file_id='fid',
                           path='path',
                           content_change=False,
                           versioned=(True, True),
                           parent_id=('pid', 'pid'),
                           name=('name', 'name'),
                           kind=('file', 'file'),
                           executable=(False, False),
                           versioned_change='unchanged',
                           renamed=False,
                           modified='unchanged',
                           exe_change=False):
        reporter = InstrumentedReporter()
        delta.report_changes([(file_id, path, content_change, versioned,
                               parent_id, name, kind, executable)], reporter)
        output = reporter.calls[0]
        self.assertEqual(file_id, output[0])
        self.assertEqual(path, output[1])
        self.assertEqual(versioned_change, output[2])
        self.assertEqual(renamed, output[3])
        self.assertEqual(modified, output[4])
        self.assertEqual(exe_change, output[5])
        self.assertEqual(kind, output[6])

    def test_report_changes(self):
        """Test change detection of report_changes"""
        #Ensure no changes are detected by default
        self.assertChangesEqual(modified='unchanged', renamed=False,
                                versioned_change='unchanged',
                                exe_change=False)
        self.assertChangesEqual(modified='kind changed',
                                kind=('file', 'directory'))
        self.assertChangesEqual(modified='created', kind=(None, 'directory'))
        self.assertChangesEqual(modified='deleted', kind=('directory', None))
        self.assertChangesEqual(content_change=True, modified='modified')
        self.assertChangesEqual(renamed=True, name=('old', 'new'))
        self.assertChangesEqual(renamed=True,
                                parent_id=('old-parent', 'new-parent'))
        self.assertChangesEqual(versioned_change='added',
                                versioned=(False, True))
        self.assertChangesEqual(versioned_change='removed',
                                versioned=(True, False))
        # execute bit is only detected as "changed" if the file is and was
        # a regular file.
        self.assertChangesEqual(exe_change=True, executable=(True, False))
        self.assertChangesEqual(exe_change=False, executable=(True, False),
                                kind=('directory', 'directory'))
        self.assertChangesEqual(exe_change=False, modified='kind changed',
                                executable=(False, True),
                                kind=('directory', 'file'))

        # Now make sure they all work together
        self.assertChangesEqual(versioned_change='removed',
                                modified='deleted', versioned=(True, False),
                                kind=('directory', None))
        self.assertChangesEqual(versioned_change='removed',
                                modified='created', versioned=(True, False),
                                kind=(None, 'file'))
        self.assertChangesEqual(versioned_change='removed',
                                modified='modified', renamed=True,
                                exe_change=True, versioned=(True, False),
                                content_change=True, name=('old', 'new'),
                                executable=(False, True))
