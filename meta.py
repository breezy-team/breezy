# Queryable plugin variables, from a proposal by Robert Collins.

bzr_plugin_name = 'bisect'

version_info = (1, 1, 0, 'pre', 0)
__version__ = '.'.join([str(x) for x in version_info[:3]])
if version_info[3] != 'final':
    __version__ = "%s%s%d" % (__version__, version_info[3], version_info[4])

bzr_minimum_api = (0, 18, 0)

bzr_commands = [ 'bisect' ]
