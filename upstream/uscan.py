#    upstream.py -- Providers of upstream source
#    Copyright (C) 2009 Canonical Ltd.
#    Copyright (C) 2009-2020 Jelmer Vernooij <jelmer@debian.org>
#
#    This file is part of brz-debian.
#
#    brz-debian is free software; you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation; either version 2 of the License, or
#    (at your option) any later version.
#
#    brz-debian is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with brz-debian; if not, write to the Free Software
#    Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA

import os
import re
import subprocess
import shutil
import sys
import tempfile

from debmutate.watch import parse_watch_file

from ....errors import BzrError
try:
    from ....transport import NoSuchFile
except ImportError:
    from ....errors import NoSuchFile
from .... import osutils
from ....trace import note, warning
from . import UpstreamSource, PackageVersionNotPresent
from ..util import export_with_nested


class UScanError(BzrError):

    _fmt = "UScan failed to run: %(errors)s."

    def __init__(self, errors):
        self.errors = errors


class NoWatchFile(BzrError):

    _fmt = "Tree %(tree)r has no watch file %(path)s."

    def __init__(self, tree, path):
        BzrError.__init__(self, tree=tree, path=path)


class WatchLineWithoutMatches(BzrError):

    _fmt = "No matching files for watch line %(line)r."

    def __init__(self, line):
        BzrError.__init__(self, line=line)


class WatchLineWithoutMatchingHrefs(PackageVersionNotPresent):

    _fmt = ("No match for %(mangled_version)s was not found "
            "for %(line)r in %(upstream)s.")

    def __init__(self, mangled_version, line, package, version, upstream):
        BzrError.__init__(self, package=package, version=version,
                          upstream=upstream, mangled_version=mangled_version,
                          line=line)


class UScanSource(UpstreamSource):
    """Upstream source that uses uscan."""

    def __init__(self, tree, subpath=None, top_level=False, auto_fix=False,
                 skip_signatures: bool = False):
        self.tree = tree
        self.subpath = subpath
        self.top_level = top_level
        self.auto_fix = auto_fix
        self.skip_signatures = skip_signatures

    def __repr__(self):
        return "<%s(%r, subpath=%r, top_level=%r, auto_fix=%r, skip_signatures=%r)>" % (
            type(self).__name__, self.tree, self.subpath, self.top_level,
            self.auto_fix, self.skip_signatures)

    @classmethod
    def from_tree(cls, tree, subpath: str, top_level: bool = False,
                  auto_fix: bool = False, skip_signatures: bool = False):
        if top_level:
            file = 'watch'
        else:
            file = 'debian/watch'
        if subpath:
            file = osutils.pathjoin(subpath, file)
        if not tree.has_filename(file):
            raise NoWatchFile(tree, file)
        return cls(tree, subpath=subpath, top_level=top_level,
                   auto_fix=auto_fix, skip_signatures=skip_signatures)

    def _export_file(self, name, directory):
        if self.top_level:
            file = name
        else:
            file = 'debian/' + name
        if self.subpath:
            file = osutils.pathjoin(self.subpath, file)
        if not self.tree.has_filename(file):
            raise NoSuchFile(file, self.tree)
        output_path = os.path.join(directory, 'debian', name)
        output_dir = os.path.dirname(output_path)
        if not os.path.isdir(output_dir):
            os.makedirs(output_dir)
        with open(output_path, 'wb') as f:
            f.write(self.tree.get_file_text(file))
        if self.auto_fix:
            self._do_auto_fix(output_path)
        return output_path

    @staticmethod
    def _do_auto_fix(path):
        from debmutate.watch import WatchEditor
        try:
            from lintian_brush.watch import fix_watch_issues
        except ModuleNotFoundError:
            warning(
                'Not auto-fixing debian/watch file, '
                'since lintian-brush is not installed.')
        else:
            with WatchEditor(path=path, allow_reformatting=True) as updater:
                fix_watch_issues(updater)

    def get_latest_version(self, package, current_version):
        with tempfile.TemporaryDirectory() as tmpdir:
            try:
                watch_tempfilename = self._export_file('watch', tmpdir)
            except NoSuchFile:
                note("No watch file to use to check latest upstream release.")
                return None, None
            args = ["--watchfile=%s" % watch_tempfilename,
                    "--package=%s" % package, "--report",
                    "--no-download",
                    "--upstream-version=%s" % current_version]
            if self.skip_signatures:
                args.append("--skip-signature")
            text, retcode = _run_dehs_uscan(args, cwd=tmpdir)
            uversionmangle = None
            with open(watch_tempfilename, 'r') as f:
                wf = parse_watch_file(f)
                if wf and wf.entries and len(wf.entries) == 1:
                    uversionmangle = getattr(
                        wf.entries[0], 'uversionmangle', None)
        unmangled_new_version = _xml_report_extract_upstream_version(text)
        if unmangled_new_version is None:
            for w in _xml_report_extract_warnings(text):
                if re.match(
                        'In (.*)/watch no matching files for watch line',
                        w.splitlines()[0]):
                    raise WatchLineWithoutMatches(w.splitlines()[1])
                raise UScanError(w)
            return None, None
        if uversionmangle is None:
            return (unmangled_new_version, unmangled_new_version)
        return unmangled_new_version, uversionmangle(unmangled_new_version)

    def get_recent_versions(self, package, since_version=None):
        raise NotImplementedError(self.get_recent_versions)

    def fetch_tarballs(self, package, version, target_dir, components=None):
        note("Using uscan to look for the upstream tarball.")
        with tempfile.TemporaryDirectory() as tmpdir:
            container = os.path.join(tmpdir, 'container')
            os.mkdir(container)
            if self.top_level:
                subdir = ''
            else:
                subdir = 'debian'
            if self.subpath:
                subdir = osutils.pathjoin(self.subpath, subdir)
            # Just export all of debian/, since e.g. uupdate needs more of it.
            export_with_nested(
                self.tree, os.path.join(container, 'debian'), format='dir',
                subdir=subdir)
            if self.auto_fix:
                self._do_auto_fix(os.path.join(container, 'debian', 'watch'))
            args = ["--force-download", "--rename",
                    "--check-dirname-level=0",
                    "--download", '--destdir=%s' % container,
                    "--download-debversion=%s" % version]
            if self.skip_signatures:
                args.append("--skip-signature")
            text, r = _run_dehs_uscan(args, cwd=container)
            _xml_report_extract_errors(text)
            orig_files = _xml_report_extract_target_paths(text)
            if not orig_files:
                for w in _xml_report_extract_warnings(text):
                    m = re.match(
                        'In (.*) no matching hrefs for version (.*) in watch '
                        'line', w.splitlines()[0])
                    if m:
                        raise WatchLineWithoutMatchingHrefs(
                            m.group(1), w.splitlines()[1],
                            package, version, self)
                    raise UScanError(w)
                raise PackageVersionNotPresent(package, version, self)
            _xml_report_print_warnings(text)
            if all([os.path.exists(p) for p in orig_files]):
                pass
            else:
                orig_files = [
                    entry.path for entry in os.scandir(tmpdir)
                    if entry.name != 'container']
                if not orig_files:
                    note("uscan could not find the needed tarballs.")
                    raise PackageVersionNotPresent(package, version, self)
            ret = []
            for src in orig_files:
                dst = os.path.join(target_dir, os.path.basename(src))
                ret.append(dst)
                shutil.copy(os.path.join(tmpdir, src), dst)

            return [src for src in ret if not src.endswith('.asc')]


def _xml_report_extract_upstream_version(text):
    _xml_report_extract_errors(text)
    from xml.sax.saxutils import unescape
    # uscan --dehs's output isn't well-formed XML, so let's fall back to
    # regexes instead..
    um = re.search(b'<upstream-version>(.*)</upstream-version>', text)
    if um:
        return unescape(um.group(1).decode())
    return None


def _xml_report_extract_target_paths(text):
    from xml.sax.saxutils import unescape
    return [
        unescape(m.group(1).decode())
        for m in re.finditer(b'<target-path>(.*)</target-path>', text)]


def _run_dehs_uscan(args, cwd):
    p = subprocess.Popen(
        ["uscan", "--dehs"] + args,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=cwd)
    (stdout, stderr) = p.communicate()
    if b'</dehs>' not in stdout:
        error = stderr.decode()
        for line in error.splitlines():
            if line.startswith('uscan warn: '):
                continue
            if line.startswith('uscan error '):
                line = line[len('uscan error '):]
            raise UScanError(line)
        raise UScanError(error)
    sys.stderr.write(stderr.decode())
    return stdout, p.returncode


def _xml_report_extract_warnings(text):
    from xml.sax.saxutils import unescape
    for m in re.finditer(
            b"<warnings>(.*?)</warnings>", text,
            flags=(re.M | re.S)):
        yield unescape(m.group(1).decode())


def _xml_report_print_warnings(text):
    for w in _xml_report_extract_warnings(text):
        warning(w)


def _xml_report_extract_errors(text):
    from xml.sax.saxutils import unescape
    lines = [unescape(m.group(1).decode())
             for m in re.finditer(
                 b"<errors>(.*?)</errors>", text,
                 flags=(re.M | re.S))]
    ignored = []
    for line in lines:
        if not line.startswith('uscan warn: '):
            raise UScanError(line)
        else:
            ignored.append(line[len('uscan warn: '):])

    for line in lines:
        raise UScanError(line)

    return ignored
