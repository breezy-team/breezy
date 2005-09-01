# Copyright (C) 2004, 2005 by Canonical Ltd

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

# TODO: Perhaps rather than mapping options and arguments back and
# forth, we should just pass in the whole argv, and allow
# ExternalCommands to handle it differently to internal commands?


from bzrlib.commands import Command


class ExternalCommand(Command):
    """Class to wrap external commands.

    The only wrinkle is that we have to map bzr's dictionary of
    options and arguments back into command line options and arguments
    for the script.
    """

    @classmethod
    def find_command(cls, cmd):
        import os.path
        bzrpath = os.environ.get('BZRPATH', '')

        for dir in bzrpath.split(os.pathsep):
            path = os.path.join(dir, cmd)
            if os.path.isfile(path):
                return ExternalCommand(path)

        return None


    def __init__(self, path):
        self.path = path

        pipe = os.popen('%s --bzr-usage' % path, 'r')
        self.takes_options = pipe.readline().split()

        for opt in self.takes_options:
            if not opt in OPTIONS:
                raise BzrError("Unknown option '%s' returned by external command %s"
                               % (opt, path))

        # TODO: Is there any way to check takes_args is valid here?
        self.takes_args = pipe.readline().split()

        if pipe.close() is not None:
            raise BzrError("Failed funning '%s --bzr-usage'" % path)

        pipe = os.popen('%s --bzr-help' % path, 'r')
        self.__doc__ = pipe.read()
        if pipe.close() is not None:
            raise BzrError("Failed funning '%s --bzr-help'" % path)

    def __call__(self, options, arguments):
        Command.__init__(self, options, arguments)
        return self

    def name(self):
        raise NotImplementedError()

    def run(self, **kargs):
        raise NotImplementedError()
        
        opts = []
        args = []

        keys = kargs.keys()
        keys.sort()
        for name in keys:
            optname = name.replace('_','-')
            value = kargs[name]
            if OPTIONS.has_key(optname):
                # it's an option
                opts.append('--%s' % optname)
                if value is not None and value is not True:
                    opts.append(str(value))
            else:
                # it's an arg, or arg list
                if type(value) is not list:
                    value = [value]
                for v in value:
                    if v is not None:
                        args.append(str(v))

        self.status = os.spawnv(os.P_WAIT, self.path, [self.path] + opts + args)
        return self.status



