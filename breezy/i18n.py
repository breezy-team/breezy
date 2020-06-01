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

# This module is copied from Bazaar Explorer and modified for brz.

"""i18n and l10n support for Bazaar."""

import gettext as _gettext
import os
import sys


_translations = None


def gettext(message):
    """Translate message.

    :returns: translated message as unicode.
    """
    install()
    try:
        return _translations.ugettext(message)
    except AttributeError:
        return _translations.gettext(message)


def ngettext(singular, plural, number):
    """Translate message with plural forms based on `number`.

    :param singular: English language message in singular form
    :param plural: English language message in plural form
    :param number: the number this message should be translated for

    :returns: translated message as unicode.
    """
    install()
    try:
        return _translations.ungettext(singular, plural, number)
    except AttributeError:
        return _translations.ngettext(singular, plural, number)


def N_(msg):
    """Mark message for translation but don't translate it right away."""
    return msg


def gettext_per_paragraph(message):
    """Translate message per paragraph.

    :returns: concatenated translated message as unicode.
    """
    install()
    paragraphs = message.split(u'\n\n')
    # Be careful not to translate the empty string -- it holds the
    # meta data of the .po file.
    return u'\n\n'.join(gettext(p) if p else u'' for p in paragraphs)


def disable_i18n():
    """Do not allow i18n to be enabled.  Useful for third party users
    of breezy."""
    global _translations
    _translations = _gettext.NullTranslations()


def installed():
    """Returns whether translations are in use or not."""
    return _translations is not None


def install(lang=None):
    """Enables gettext translations in brz."""
    global _translations
    if installed():
        return
    _translations = install_translations(lang)


def install_translations(lang=None, domain='brz', locale_base=None):
    """Create a gettext translation object.

    :param lang: language to install.
    :param domain: translation domain to install.
    :param locale_base: plugins can specify their own directory.

    :returns: a gettext translations object to use
    """
    if lang is None:
        lang = _get_current_locale()
    if lang is not None:
        languages = lang.split(':')
    else:
        languages = None
    translation = _gettext.translation(
        domain,
        localedir=_get_locale_dir(locale_base),
        languages=languages,
        fallback=True)
    return translation


def add_fallback(fallback):
    """
    Add a fallback translations object.  Typically used by plugins.

    :param fallback: gettext.GNUTranslations object
    """
    install()
    _translations.add_fallback(fallback)


def uninstall():
    """Disables gettext translations."""
    global _translations
    _translations = None


def _get_locale_dir(base):
    """Returns directory to find .mo translations file in, either local or system

    :param base: plugins can specify their own local directory
    """
    if getattr(sys, 'frozen', False):
        if base is None:
            base = os.path.dirname(sys.executable)
        return os.path.join(base, u'locale')
    else:
        if base is None:
            base = os.path.dirname(__file__)
        dirpath = os.path.realpath(os.path.join(base, u'locale'))
        if os.path.exists(dirpath):
            return dirpath
    return os.path.join(sys.prefix, u"share", u"locale")


def _check_win32_locale():
    for i in ('LANGUAGE', 'LC_ALL', 'LC_MESSAGES', 'LANG'):
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
        from . import config
        lang = config.GlobalStack().get('language')
        if lang:
            os.environ['LANGUAGE'] = lang
            return lang
    if sys.platform == 'win32':
        _check_win32_locale()
    for i in ('LANGUAGE', 'LC_ALL', 'LC_MESSAGES', 'LANG'):
        lang = os.environ.get(i)
        if lang:
            return lang
    return None


def load_plugin_translations(domain):
    """Load the translations for a specific plugin.

    :param domain: Gettext domain name (usually 'brz-PLUGINNAME')
    """
    locale_base = os.path.dirname(__file__)
    translation = install_translations(domain=domain,
                                       locale_base=locale_base)
    add_fallback(translation)
    return translation
