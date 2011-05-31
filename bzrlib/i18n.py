# -*- coding: utf-8 -*-
#
# Copyright (C) 2007 Lukáš Lalinský <lalinsky@gmail.com>
# Copyright (C) 2007,2009 Alexander Belchenko <bialix@ukr.net>
# Copyright (C) 2011 Canonical Ltd
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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

# This module is copied from Bazaar Explorer and modified for bzr.

"""i18n and l10n support for Bazaar."""

import gettext as _gettext
import os
import sys

_translation = _gettext.NullTranslations()


def gettext(message):
    """Translate message. 
    
    :returns: translated message as unicode.
    """
    return _translation.ugettext(message)


def ngettext(s, p, n):
    """Translate message based on `n`.

    :returns: translated message as unicode.
    """
    return _translation.ungettext(s, p, n)


def N_(msg):
    """Mark message for translation but don't translate it right away."""
    return msg


def gettext_per_paragraph(message):
    """Translate message per paragraph.

    :returns: concatenated translated message as unicode.
    """
    paragraphs = message.split(u'\n\n')
    ugettext = _translation.ugettext
    # Be careful not to translate the empty string -- it holds the
    # meta data of the .po file.
    return u'\n\n'.join(ugettext(p) if p else u'' for p in paragraphs)


def install(lang=None):
    global _translation
    if lang is None:
        lang = _get_current_locale()
    _translation = _gettext.translation(
            'bzr',
            localedir=_get_locale_dir(),
            languages=lang.split(':'),
            fallback=True)


def uninstall():
    global _translation
    _translation = _null_translation


def _get_locale_dir():
    if hasattr(sys, 'frozen'):
        base = os.path.dirname(
                unicode(sys.executable, sys.getfilesystemencoding()))
        return os.path.join(base, u'locale')
    else:
        base = os.path.dirname(unicode(__file__, sys.getfilesystemencoding()))
        dirpath = os.path.realpath(os.path.join(base, u'locale'))
        if os.path.exists(dirpath):
            return dirpath
        else:
            return '/usr/share/locale'


def _check_win32_locale():
    for i in ('LANGUAGE','LC_ALL','LC_MESSAGES','LANG'):
        if os.environ.get(i):
            break
    else:
        lang = None
        import locale
        try:
            import ctypes
        except ImportError:
            # use only user's default locale
            lang = locale.getdefaultlocale()[0]
        else:
            # using ctypes to determine all locales
            lcid_user = ctypes.windll.kernel32.GetUserDefaultLCID()
            lcid_system = ctypes.windll.kernel32.GetSystemDefaultLCID()
            if lcid_user != lcid_system:
                lcid = [lcid_user, lcid_system]
            else:
                lcid = [lcid_user]
            lang = [locale.windows_locale.get(i) for i in lcid]
            lang = ':'.join([i for i in lang if i])
        # set lang code for gettext
        if lang:
            os.environ['LANGUAGE'] = lang


def _get_current_locale():
    if not os.environ.get('LANGUAGE'):
        from bzrlib import config
        lang = config.GlobalConfig().get_user_option('language')
        if lang:
            os.environ['LANGUAGE'] = lang
            return lang
    if sys.platform == 'win32':
        _check_win32_locale()
    for i in ('LANGUAGE','LC_ALL','LC_MESSAGES','LANG'):
        lang = os.environ.get(i)
        if lang:
            return lang
    return None
