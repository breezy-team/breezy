# Copyright (C) 2008 Canonical Ltd
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

"""Fast, stream-based importing of data into Bazaar."""


from bzrlib.commands import Command, register_command
from bzrlib.option import RegistryOption, ListOption


def test_suite():
    import tests
    return tests.test_suite()


def _defines_to_dict(defines):
    """Convert a list of definition strings to a dictionary."""
    if defines is None:
        return None
    result = {}
    for define in defines:
        kv = define.split('=', 1)
        if len(kv) == 1:
            result[define.strip()] = 1
        else:
            result[kv[0].strip()] = kv[1].strip()
    return result


class cmd_fast_import(Command):
    """Backend for fast Bazaar data importers.

    This command reads a mixed command/data stream from standard
    input and creates branches in the current repository. It is
    designed to be stream compatible with git-fast-import so that
    existing front-ends can be reused with a minimum of modifications.
    Git 1.5.4 includes git-fast-export enabling conversion from git.
    See http://git.or.cz/gitwiki/InterfacesFrontendsAndTools for
    other front-ends including converters from Subversion, CVS,
    Mercurial, Darcs, Perforce and SCCS. See
    http://www.kernel.org/pub/software/scm/git/docs/git-fast-import.html
    for the protocol specification. See the documentation shipped
    with the bzr-fastimport plugin for the known limitations and
    Bazaar-specific enhancements.

    Examples::

     cd /git/repo/path
     git-fast-export --signed-tags=warn | bzr fast-import

        Import a Git repository into Bazaar.

     svn-fast-export.py /svn/repo/path | bzr fast-import

        Import a Subversion repository into Bazaar.

     hg-fast-export.py -r /hg/repo/path | bzr fast-import

        Import a Mercurial repository into Bazaar.
    """
    hidden = True
    takes_args = []
    takes_options = ['verbose',
                    RegistryOption.from_kwargs('method',
                        'The way to process the data.',
                        title='Processing Method',
                        value_switches=True, enum_switch=False,
                        safe="Import the data into any format (default).",
                        info="Display information only - don't import it.",
                        ),
                    ListOption('params', short_name='P', type=str,
                        help="Define processing specific parameters.",
                        ),
                     ]
    aliases = ['fastimport']
    def run(self, verbose=False, method='safe', params=None):
        import sys
        from bzrlib import bzrdir
        import parser

        params = _defines_to_dict(params)
        if method == 'info':
            from bzrlib.plugins.fastimport.processors import info_processor
            proc = info_processor.InfoProcessor(params=params)
        else:
            from bzrlib.plugins.fastimport.processors import generic_processor
            control, relpath = bzrdir.BzrDir.open_containing('.')
            proc = generic_processor.GenericProcessor(control, params=params)

        # Note: might need to pass the parser to the processor so that the
        # processor can be it's error reporting with source context
        p = parser.ImportParser(sys.stdin, verbose=verbose)
        return proc.process(p.iter_commands)


register_command(cmd_fast_import)
