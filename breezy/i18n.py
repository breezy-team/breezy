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

import os
import sys

from ._cmd_rs import i18n as _i18n_rs

install_zzz = _i18n_rs.install_zzz
install_zzz_for_doc = _i18n_rs.install_zzz_for_doc
zzz = _i18n_rs.zzz


def disable_i18n():
    """Disable i18n support.

    This is useful for testing.
    """
    _i18n_rs.disable_i18n()


def gettext(message):
    """Translate message.

    :returns: translated message as unicode.
    """
    install()
    return _i18n_rs.gettext(message)


def ngettext(singular, plural, number):
    """Translate message with plural forms based on `number`.

    :param singular: English language message in singular form
    :param plural: English language message in plural form
    :param number: the number this message should be translated for

    :returns: translated message as unicode.
    """
    return _i18n_rs.ngettext(singular, plural, number)


def N_(msg):
    """Mark message for translation but don't translate it right away."""
    return msg


gettext_per_paragraph = _i18n_rs.gettext_per_paragraph


_installed = False


def install(lang=None):
    """Enables gettext translations in brz."""
    global _installed
    if _installed:
        return
    if lang is None:
        lang = _get_current_locale()
    if lang == "C":
        # Nothing to be done for C locale
        _i18n_rs.i18n_disable_i18n()
    else:
        try:
            _i18n_rs.install(lang, _get_locale_dir())
        except Exception as err:
            # We don't have translation files for "en" or "en_US" locales
            if not lang.startswith("en"):
                # Missing translation is not a fatal error, just report it
                sys.stderr.write(
                    f"Cannot install translation for locale \"{lang}\": {err}\n")
    _installed = True


def _get_locale_dir():
    """Returns directory to find .mo translations file in, either local or system.

    :param base: plugins can specify their own local directory
    """
    base = os.path.dirname(__file__)
    dirpath = os.path.realpath(os.path.join(base, "locale"))
    if os.path.exists(dirpath):
        return dirpath
    return os.path.join(sys.prefix, "share", "locale")


def _check_win32_locale():
    for i in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        if os.environ.get(i):
            break
    else:
        lang = None
        import locale

        try:
            import ctypes
        except ModuleNotFoundError:
            # use only user's default locale
            lang = locale.getdefaultlocale()[0]
        else:
            # using ctypes to determine all locales
            lcid_user = ctypes.windll.kernel32.GetUserDefaultLCID()
            lcid_system = ctypes.windll.kernel32.GetSystemDefaultLCID()
            lcid = [lcid_user, lcid_system] if lcid_user != lcid_system else [lcid_user]
            lang = [locale.windows_locale.get(i) for i in lcid]
            lang = ":".join([i for i in lang if i])
        # set lang code for gettext
        if lang:
            os.environ["LANGUAGE"] = lang


def _get_current_locale():
    if not os.environ.get("LANGUAGE"):
        from . import config

        lang = config.GlobalStack().get("language")
        if lang:
            os.environ["LANGUAGE"] = lang
            return lang
    if sys.platform == "win32":
        _check_win32_locale()
    for i in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        lang = os.environ.get(i)
        if lang:
            return lang
    return None


class Domain:
    def __init__(self, domain):
        self.domain = domain

    def gettext(self, message):
        return _i18n_rs.dgettext(self.domain, message)


def load_plugin_translations(domain):
    """Load the translations for a specific plugin.

    :param domain: Gettext domain name (usually 'brz-PLUGINNAME')
    """
    _i18n_rs.install_plugin(domain)
    return Domain(domain)
