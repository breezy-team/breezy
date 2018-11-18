# Copyright (C) 2006, 2009, 2010, 2011 Canonical Ltd
# -*- coding: utf-8 -*-
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

"""Adapter for running test cases against multiple encodings."""

# prefix for micro (1/1000000)
_mu = u'\xb5'

# greek letter omega, not to be confused with
# the Ohm sign, u'\u2126'. Though they are probably identical
# cp437 can handle the first, but not the second
_omega = u'\u03a9'

# smallest error possible, epsilon
# cp437 handles u03b5, but not u2208 the 'element of' operator
_epsilon = u'\u03b5'

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
# The word 'test' in Russian
_russian_test = u'\u0422\u0435\u0441\u0442'

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
_yellow = u'\u017dlu\u0165ou\u010dk\xfd'
_someone = u'Some\u016f\u0148\u011b'
_something = u'\u0165ou\u010dk\xfd'

# Hebrew
# Shalom -> 'hello' or 'peace', used as a common greeting
_shalom = u'\u05e9\u05dc\u05d5\u05dd'


encoding_scenarios = [
    # Permutation 1 of utf-8
    ('utf-8,1', {
        'info': {
            'committer': _erik,
            'message': _yellow_horse,
            'filename': _shrimp_sandwich,
            'directory': _nihonjin,
            },
        'encoding': 'utf-8',
        }),
    # Permutation 2 of utf-8
    ('utf-8,2', {
        'info': {
            'committer': _alexander,
            'message': u'Testing ' + _mu,
            'filename': _shalom,
            'directory': _juju,
            },
        'encoding': 'utf-8',
        }),
    ('iso-8859-1', {
        'info': {
            'committer': _erik,
            'message': u'Testing ' + _mu,
            'filename': _juju_alt,
            'directory': _shrimp_sandwich,
            },
        'encoding': 'iso-8859-1',
        }),
    ('iso-8859-2', {
        'info': {
            'committer': _someone,
            'message': _yellow_horse,
            'filename': _yellow,
            'directory': _something,
            },
        'encoding': 'iso-8859-2',
        }),
    ('cp1251', {
        'info': {
            'committer': _alexander,
            'message': u'Testing ' + _mu,
            'filename': _russian_test,
            'directory': _russian_test + 'dir',
            },
        'encoding': 'cp1251',
        }),
    # The iso-8859-1 tests run on a default windows cp437 installation
    # and it takes a long time to run an extra permutation of the tests
    # But just in case we want to add this back in:
    #        ('cp437', {'committer':_erik
    #                  , 'message':u'Testing ' + _mu
    #                  , 'filename':'file_' + _omega
    #                  , 'directory':_epsilon + '_dir',
    #            'encoding': 'cp437'}),
    ]
