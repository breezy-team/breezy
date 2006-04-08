# Copyright (C) 2005 by Canonical Ltd
#
# Authors:
#   Johan Rydberg <jrydberg@gnu.org>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

# Remaing to do is to figure out if get_graph should return a simple
# map, or a graph object of some kind.


"""Versioned text file storage api."""


from copy import deepcopy
from unittest import TestSuite


import bzrlib.errors as errors
from bzrlib.inter import InterObject
from bzrlib.symbol_versioning import *
from bzrlib.textmerge import TextMerge
from bzrlib.transport.memory import MemoryTransport
from bzrlib.tsort import topo_sort
from bzrlib import ui


class VersionedFile(object):
    """Versioned text file storage.
    
    A versioned file manages versions of line-based text files,
    keeping track of the originating version for each line.

    To clients the "lines" of the file are represented as a list of
    strings. These strings will typically have terminal newline
    characters, but this is not required.  In particular files commonly
    do not have a newline at the end of the file.

    Texts are identified by a version-id string.
    """

    def __init__(self, access_mode):
        self.finished = False
        self._access_mode = access_mode

    def copy_to(self, name, transport):
        """Copy this versioned file to name on transport."""
        raise NotImplementedError(self.copy_to)
    
    @deprecated_method(zero_eight)
    def names(self):
        """Return a list of all the versions in this versioned file.

        Please use versionedfile.versions() now.
        """
        return self.versions()

    def versions(self):
        """Return a unsorted list of versions."""
        raise NotImplementedError(self.versions)

    def has_ghost(self, version_id):
        """Returns whether version is present as a ghost."""
        raise NotImplementedError(self.has_ghost)

    def has_version(self, version_id):
        """Returns whether version is present."""
        raise NotImplementedError(self.has_version)

    def add_delta(self, version_id, parents, delta_parent, sha1, noeol, delta):
        """Add a text to the versioned file via a pregenerated delta.

        :param version_id: The version id being added.
        :param parents: The parents of the version_id.
        :param delta_parent: The parent this delta was created against.
        :param sha1: The sha1 of the full text.
        :param delta: The delta instructions. See get_delta for details.
        """
        self._check_write_ok()
        if self.has_version(version_id):
            raise errors.RevisionAlreadyPresent(version_id, self)
        return self._add_delta(version_id, parents, delta_parent, sha1, noeol, delta)

    def _add_delta(self, version_id, parents, delta_parent, sha1, noeol, delta):
        """Class specific routine to add a delta.

        This generic version simply applies the delta to the delta_parent and
        then inserts it.
        """
        # strip annotation from delta
        new_delta = []
        for start, stop, delta_len, delta_lines in delta:
            new_delta.append((start, stop, delta_len, [text for origin, text in delta_lines]))
        if delta_parent is not None:
            parent_full = self.get_lines(delta_parent)
        else:
            parent_full = []
        new_full = self._apply_delta(parent_full, new_delta)
        # its impossible to have noeol on an empty file
        if noeol and new_full[-1][-1] == '\n':
            new_full[-1] = new_full[-1][:-1]
        self.add_lines(version_id, parents, new_full)

    def add_lines(self, version_id, parents, lines, parent_texts=None):
        """Add a single text on top of the versioned file.

        Must raise RevisionAlreadyPresent if the new version is
        already present in file history.

        Must raise RevisionNotPresent if any of the given parents are
        not present in file history.
        :param parent_texts: An optional dictionary containing the opaque 
             representations of some or all of the parents of 
             version_id to allow delta optimisations. 
             VERY IMPORTANT: the texts must be those returned
             by add_lines or data corruption can be caused.
        :return: An opaque representation of the inserted version which can be
                 provided back to future add_lines calls in the parent_texts
                 dictionary.
        """
        self._check_write_ok()
        return self._add_lines(version_id, parents, lines, parent_texts)

    def _add_lines(self, version_id, parents, lines, parent_texts):
        """Helper to do the class specific add_lines."""
        raise NotImplementedError(self.add_lines)

    def add_lines_with_ghosts(self, version_id, parents, lines,
                              parent_texts=None):
        """Add lines to the versioned file, allowing ghosts to be present.
        
        This takes the same parameters as add_lines.
        """
        self._check_write_ok()
        return self._add_lines_with_ghosts(version_id, parents, lines,
                                           parent_texts)

    def _add_lines_with_ghosts(self, version_id, parents, lines, parent_texts):
        """Helper to do class specific add_lines_with_ghosts."""
        raise NotImplementedError(self.add_lines_with_ghosts)

    def check(self, progress_bar=None):
        """Check the versioned file for integrity."""
        raise NotImplementedError(self.check)

    def _check_write_ok(self):
        """Is the versioned file marked as 'finished' ? Raise if it is."""
        if self.finished:
            raise errors.OutSideTransaction()
        if self._access_mode != 'w':
            raise errors.ReadOnlyObjectDirtiedError(self)

    def clear_cache(self):
        """Remove any data cached in the versioned file object."""

    def clone_text(self, new_version_id, old_version_id, parents):
        """Add an identical text to old_version_id as new_version_id.

        Must raise RevisionNotPresent if the old version or any of the
        parents are not present in file history.

        Must raise RevisionAlreadyPresent if the new version is
        already present in file history."""
        self._check_write_ok()
        return self._clone_text(new_version_id, old_version_id, parents)

    def _clone_text(self, new_version_id, old_version_id, parents):
        """Helper function to do the _clone_text work."""
        raise NotImplementedError(self.clone_text)

    def create_empty(self, name, transport, mode=None):
        """Create a new versioned file of this exact type.

        :param name: the file name
        :param transport: the transport
        :param mode: optional file mode.
        """
        raise NotImplementedError(self.create_empty)

    def fix_parents(self, version, new_parents):
        """Fix the parents list for version.
        
        This is done by appending a new version to the index
        with identical data except for the parents list.
        the parents list must be a superset of the current
        list.
        """
        self._check_write_ok()
        return self._fix_parents(version, new_parents)

    def _fix_parents(self, version, new_parents):
        """Helper for fix_parents."""
        raise NotImplementedError(self.fix_parents)

    def get_delta(self, version):
        """Get a delta for constructing version from some other version.
        
        :return: (delta_parent, sha1, noeol, delta)
        Where delta_parent is a version id or None to indicate no parent.
        """
        raise NotImplementedError(self.get_delta)

    def get_deltas(self, versions):
        """Get multiple deltas at once for constructing versions.
        
        :return: dict(version_id:(delta_parent, sha1, noeol, delta))
        Where delta_parent is a version id or None to indicate no parent, and
        version_id is the version_id created by that delta.
        """
        result = {}
        for version in versions:
            result[version] = self.get_delta(version)
        return result

    def get_suffixes(self):
        """Return the file suffixes associated with this versioned file."""
        raise NotImplementedError(self.get_suffixes)
    
    def get_text(self, version_id):
        """Return version contents as a text string.

        Raises RevisionNotPresent if version is not present in
        file history.
        """
        return ''.join(self.get_lines(version_id))
    get_string = get_text

    def get_lines(self, version_id):
        """Return version contents as a sequence of lines.

        Raises RevisionNotPresent if version is not present in
        file history.
        """
        raise NotImplementedError(self.get_lines)

    def get_ancestry(self, version_ids):
        """Return a list of all ancestors of given version(s). This
        will not include the null revision.

        Must raise RevisionNotPresent if any of the given versions are
        not present in file history."""
        if isinstance(version_ids, basestring):
            version_ids = [version_ids]
        raise NotImplementedError(self.get_ancestry)
        
    def get_ancestry_with_ghosts(self, version_ids):
        """Return a list of all ancestors of given version(s). This
        will not include the null revision.

        Must raise RevisionNotPresent if any of the given versions are
        not present in file history.
        
        Ghosts that are known about will be included in ancestry list,
        but are not explicitly marked.
        """
        raise NotImplementedError(self.get_ancestry_with_ghosts)
        
    def get_graph(self):
        """Return a graph for the entire versioned file.
        
        Ghosts are not listed or referenced in the graph.
        """
        result = {}
        for version in self.versions():
            result[version] = self.get_parents(version)
        return result

    def get_graph_with_ghosts(self):
        """Return a graph for the entire versioned file.
        
        Ghosts are referenced in parents list but are not
        explicitly listed.
        """
        raise NotImplementedError(self.get_graph_with_ghosts)

    @deprecated_method(zero_eight)
    def parent_names(self, version):
        """Return version names for parents of a version.
        
        See get_parents for the current api.
        """
        return self.get_parents(version)

    def get_parents(self, version_id):
        """Return version names for parents of a version.

        Must raise RevisionNotPresent if version is not present in
        file history.
        """
        raise NotImplementedError(self.get_parents)

    def get_parents_with_ghosts(self, version_id):
        """Return version names for parents of version_id.

        Will raise RevisionNotPresent if version_id is not present
        in the history.

        Ghosts that are known about will be included in the parent list,
        but are not explicitly marked.
        """
        raise NotImplementedError(self.get_parents_with_ghosts)

    def annotate_iter(self, version_id):
        """Yield list of (version-id, line) pairs for the specified
        version.

        Must raise RevisionNotPresent if any of the given versions are
        not present in file history.
        """
        raise NotImplementedError(self.annotate_iter)

    def annotate(self, version_id):
        return list(self.annotate_iter(version_id))

    def _apply_delta(self, lines, delta):
        """Apply delta to lines."""
        lines = list(lines)
        offset = 0
        for start, end, count, delta_lines in delta:
            lines[offset+start:offset+end] = delta_lines
            offset = offset + (start - end) + count
        return lines

    def join(self, other, pb=None, msg=None, version_ids=None,
             ignore_missing=False):
        """Integrate versions from other into this versioned file.

        If version_ids is None all versions from other should be
        incorporated into this versioned file.

        Must raise RevisionNotPresent if any of the specified versions
        are not present in the other files history unless ignore_missing
        is supplied when they are silently skipped.
        """
        self._check_write_ok()
        return InterVersionedFile.get(other, self).join(
            pb,
            msg,
            version_ids,
            ignore_missing)

    def iter_lines_added_or_present_in_versions(self, version_ids=None):
        """Iterate over the lines in the versioned file from version_ids.

        This may return lines from other versions, and does not return the
        specific version marker at this point. The api may be changed
        during development to include the version that the versioned file
        thinks is relevant, but given that such hints are just guesses,
        its better not to have it if we dont need it.

        NOTES: Lines are normalised: they will all have \n terminators.
               Lines are returned in arbitrary order.
        """
        raise NotImplementedError(self.iter_lines_added_or_present_in_versions)

    def transaction_finished(self):
        """The transaction that this file was opened in has finished.

        This records self.finished = True and should cause all mutating
        operations to error.
        """
        self.finished = True

    @deprecated_method(zero_eight)
    def walk(self, version_ids=None):
        """Walk the versioned file as a weave-like structure, for
        versions relative to version_ids.  Yields sequence of (lineno,
        insert, deletes, text) for each relevant line.

        Must raise RevisionNotPresent if any of the specified versions
        are not present in the file history.

        :param version_ids: the version_ids to walk with respect to. If not
                            supplied the entire weave-like structure is walked.

        walk is deprecated in favour of iter_lines_added_or_present_in_versions
        """
        raise NotImplementedError(self.walk)

    @deprecated_method(zero_eight)
    def iter_names(self):
        """Walk the names list."""
        return iter(self.versions())

    def plan_merge(versionedfile, ver_a, ver_b):
        return PlanWeaveMerge.plan_merge(versionedfile, ver_a, ver_b)

    def weave_merge(self, plan, a_marker='<<<<<<< \n', b_marker='>>>>>>> \n'):
        return PlanWeaveMerge(plan, a_marker, b_marker).merge_lines()

class PlanWeaveMerge(TextMerge):
    def __init__(self, plan, a_marker='<<<<<<< \n', b_marker='>>>>>>> \n'):
        TextMerge.__init__(self, a_marker, b_marker)
        self.plan = plan

    @staticmethod
    def plan_merge(versionedfile, ver_a, ver_b):
        """Return pseudo-annotation indicating how the two versions merge.

        This is computed between versions a and b and their common
        base.

        Weave lines present in none of them are skipped entirely.
        """
        inc_a = set(versionedfile.get_ancestry([ver_a]))
        inc_b = set(versionedfile.get_ancestry([ver_b]))
        inc_c = inc_a & inc_b

        for lineno, insert, deleteset, line in\
            versionedfile.walk([ver_a, ver_b]):
            if deleteset & inc_c:
                # killed in parent; can't be in either a or b
                # not relevant to our work
                yield 'killed-base', line
            elif insert in inc_c:
                # was inserted in base
                killed_a = bool(deleteset & inc_a)
                killed_b = bool(deleteset & inc_b)
                if killed_a and killed_b:
                    yield 'killed-both', line
                elif killed_a:
                    yield 'killed-a', line
                elif killed_b:
                    yield 'killed-b', line
                else:
                    yield 'unchanged', line
            elif insert in inc_a:
                if deleteset & inc_a:
                    yield 'ghost-a', line
                else:
                    # new in A; not in B
                    yield 'new-a', line
            elif insert in inc_b:
                if deleteset & inc_b:
                    yield 'ghost-b', line
                else:
                    yield 'new-b', line
            else:
                # not in either revision
                yield 'irrelevant', line

        yield 'unchanged', ''           # terminator

    def _merge_struct(self):
        lines_a = []
        lines_b = []
        ch_a = ch_b = False
        # TODO: Show some version information (e.g. author, date) on 
        # conflicted regions.
        
        # We previously considered either 'unchanged' or 'killed-both' lines
        # to be possible places to resynchronize.  However, assuming agreement
        # on killed-both lines may be too agressive. -- mbp 20060324
        for state, line in self.plan:
            if state == 'unchanged':
                # resync and flush queued conflicts changes if any
                if not lines_a and not lines_b:
                    pass
                elif ch_a and not ch_b:
                    # one-sided change:
                    yield(lines_a,)
                elif ch_b and not ch_a:
                    yield (lines_b,)
                elif lines_a == lines_b:
                    yield(lines_a,)
                else:
                    yield (lines_a, lines_b)

                del lines_a[:]
                del lines_b[:]
                ch_a = ch_b = False
                
            if state == 'unchanged':
                if line:
                    yield ([line],)
            elif state == 'killed-a':
                ch_a = True
                lines_b.append(line)
            elif state == 'killed-b':
                ch_b = True
                lines_a.append(line)
            elif state == 'new-a':
                ch_a = True
                lines_a.append(line)
            elif state == 'new-b':
                ch_b = True
                lines_b.append(line)
            else:
                assert state in ('irrelevant', 'ghost-a', 'ghost-b', 
                                 'killed-base', 'killed-both'), state


class WeaveMerge(PlanWeaveMerge):
    def __init__(self, versionedfile, ver_a, ver_b, 
        a_marker='<<<<<<< \n', b_marker='>>>>>>> \n'):
        plan = self.plan_merge(versionedfile, ver_a, ver_b)
        PlanWeaveMerge.__init__(self, plan, a_marker, b_marker)


class InterVersionedFile(InterObject):
    """This class represents operations taking place between two versionedfiles..

    Its instances have methods like join, and contain
    references to the source and target versionedfiles these operations can be 
    carried out on.

    Often we will provide convenience methods on 'versionedfile' which carry out
    operations with another versionedfile - they will always forward to
    InterVersionedFile.get(other).method_name(parameters).
    """

    _optimisers = set()
    """The available optimised InterVersionedFile types."""

    def join(self, pb=None, msg=None, version_ids=None, ignore_missing=False):
        """Integrate versions from self.source into self.target.

        If version_ids is None all versions from source should be
        incorporated into this versioned file.

        Must raise RevisionNotPresent if any of the specified versions
        are not present in the other files history unless ignore_missing is 
        supplied when they are silently skipped.
        """
        # the default join: 
        # - if the target is empty, just add all the versions from 
        #   source to target, otherwise:
        # - make a temporary versioned file of type target
        # - insert the source content into it one at a time
        # - join them
        if not self.target.versions():
            target = self.target
        else:
            # Make a new target-format versioned file. 
            temp_source = self.target.create_empty("temp", MemoryTransport())
            target = temp_source
        graph = self.source.get_graph()
        order = topo_sort(graph.items())
        pb = ui.ui_factory.nested_progress_bar()
        parent_texts = {}
        try:
            # TODO for incremental cross-format work:
            # make a versioned file with the following content:
            # all revisions we have been asked to join
            # all their ancestors that are *not* in target already.
            # the immediate parents of the above two sets, with 
            # empty parent lists - these versions are in target already
            # and the incorrect version data will be ignored.
            # TODO: for all ancestors that are present in target already,
            # check them for consistent data, this requires moving sha1 from
            # 
            # TODO: remove parent texts when they are not relevant any more for 
            # memory pressure reduction. RBC 20060313
            # pb.update('Converting versioned data', 0, len(order))
            # deltas = self.source.get_deltas(order)
            for index, version in enumerate(order):
                pb.update('Converting versioned data', index, len(order))
                parent_text = target.add_lines(version,
                                               self.source.get_parents(version),
                                               self.source.get_lines(version),
                                               parent_texts=parent_texts)
                parent_texts[version] = parent_text
                #delta_parent, sha1, noeol, delta = deltas[version]
                #target.add_delta(version,
                #                 self.source.get_parents(version),
                #                 delta_parent,
                #                 sha1,
                #                 noeol,
                #                 delta)
                #target.get_lines(version)
            
            # this should hit the native code path for target
            if target is not self.target:
                return self.target.join(temp_source,
                                        pb,
                                        msg,
                                        version_ids,
                                        ignore_missing)
        finally:
            pb.finished()


class InterVersionedFileTestProviderAdapter(object):
    """A tool to generate a suite testing multiple inter versioned-file classes.

    This is done by copying the test once for each interversionedfile provider
    and injecting the transport_server, transport_readonly_server,
    versionedfile_factory and versionedfile_factory_to classes into each copy.
    Each copy is also given a new id() to make it easy to identify.
    """

    def __init__(self, transport_server, transport_readonly_server, formats):
        self._transport_server = transport_server
        self._transport_readonly_server = transport_readonly_server
        self._formats = formats
    
    def adapt(self, test):
        result = TestSuite()
        for (interversionedfile_class,
             versionedfile_factory,
             versionedfile_factory_to) in self._formats:
            new_test = deepcopy(test)
            new_test.transport_server = self._transport_server
            new_test.transport_readonly_server = self._transport_readonly_server
            new_test.interversionedfile_class = interversionedfile_class
            new_test.versionedfile_factory = versionedfile_factory
            new_test.versionedfile_factory_to = versionedfile_factory_to
            def make_new_test_id():
                new_id = "%s(%s)" % (new_test.id(), interversionedfile_class.__name__)
                return lambda: new_id
            new_test.id = make_new_test_id()
            result.addTest(new_test)
        return result

    @staticmethod
    def default_test_list():
        """Generate the default list of interversionedfile permutations to test."""
        from bzrlib.weave import WeaveFile
        from bzrlib.knit import KnitVersionedFile
        result = []
        # test the fallback InterVersionedFile from weave to annotated knits
        result.append((InterVersionedFile, 
                       WeaveFile,
                       KnitVersionedFile))
        for optimiser in InterVersionedFile._optimisers:
            result.append((optimiser,
                           optimiser._matching_file_factory,
                           optimiser._matching_file_factory
                           ))
        # if there are specific combinations we want to use, we can add them 
        # here.
        return result
