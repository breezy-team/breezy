# Copyright (C) 2006 by Canonical Ltd
# -*- coding: utf-8 -*-

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

"""\
Adapter for running test cases against multiple encodings.
"""

from copy import deepcopy

from bzrlib.tests import TestSuite

# prefix for micro (1/1000)
_mu = u'\xb5'

# Swedish?
_erik = u'Erik B\xe5gfors'

# Swedish 'räksmörgås' means shrimp sandwich
_shrimp_sandwich = u'r\xe4ksm\xf6rg\xe5s'

# Arabic, probably only Unicode encodings can handle this one
_juju = u'\u062c\u0648\u062c\u0648'

# iso-8859-1 alternative for juju
_juju_alt = u'j\xfbj\xfa'

# Russian, 'Alexander' in russian
_alexander = u'\u0410\u043b\u0435\u043a\u0441\u0430\u043d\u0434\u0440'

# Kanji
# It is a kanji sequence for nihonjin, or Japanese in English.
# 
# '\u4eba' being person, 'u\65e5' sun and '\u672c' origin. Ie,
# sun-origin-person, 'native from the land where the sun rises'. Note, I'm
# not a fluent speaker, so this is just my crude breakdown.
# 
# Wouter van Heyst
_nihonjin = u'\u65e5\u672c\u4eba'

# Czech
# It's what is usually used for showing how fonts look, because it contains
# most accented characters, ie. in places where Englishman use 'Quick brown fox
# jumped over a lazy dog'. The literal translation of the Czech version would
# be something like 'Yellow horse groaned devilish codes'. Actually originally
# the last word used to be 'ódy' (odes). The 'k' was added as a pun when using
# the sentece to check whether one has properly set encoding.
_yellow_horse = (u'\u017dlu\u0165ou\u010dk\xfd k\u016f\u0148'
                 u' \xfap\u011bl \u010f\xe1belsk\xe9 k\xf3dy')


class EncodingTestAdapter(object):
    """A tool to generate a suite, testing multiple encodings for a single test.
    
    This is similar to bzrlib.transport.TransportTestProviderAdapter.
    It is done by copying the test once for each encoding, and injecting
    the encoding name, and the list of valid strings for that encoding.
    Each copy is also given a new id() to make it easy to identify.
    """

    _encodings = [
        # Permutation 1 of utf-8
        ('utf-8', {'committer':_erik
                  , 'message':_yellow_horse
                  , 'filename':_shrimp_sandwich
                  , 'directory':_nihonjin}),
        # Permutation 2 of utf-8
        ('utf-8', {'committer':_alexander
                  , 'message':u'Testing ' + _mu
                  , 'filename':_juju
                  , 'directory':_juju_alt}),
        ('iso-8859-1', {'committer':_erik
                  , 'message':u'Testing ' + _mu
                  , 'filename':_juju_alt
                  , 'directory':_shrimp_sandwich}),
        ('iso-8859-2', {'committer':'TODO-iso8859-2-committer'
                  , 'message':_yellow_horse
                  , 'filename':'TODO-iso8859-2-filename'
                  , 'directory':'TODO-iso8859-2-dir'}),
        ('cp1251', {'committer':_alexander
                  , 'message':u'Testing ' + _mu
                  , 'filename':'TODO-cp1251-filename'
                  , 'directory':'TODO-cp1251-dir'}),
    ]

    def adapt(self, test):
        result = TestSuite()
        for encoding, info in self._encodings:
            new_test = deepcopy(test)
            new_test.encoding = encoding
            new_test.info = info
            def make_new_test_id():
                new_id = "%s(%s)" % (new_test.id(), encoding)
                return lambda: new_id
            new_test.id = make_new_test_id()
            result.addTest(new_test)
        return result


