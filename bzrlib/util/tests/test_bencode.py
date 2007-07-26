# bencode structured encoding
#
# Written by Petru Paler
#
# Permission is hereby granted, free of charge, to any person
# obtaining a copy of this software and associated documentation files
# (the "Software"), to deal in the Software without restriction,
# including without limitation the rights to use, copy, modify, merge,
# publish, distribute, sublicense, and/or sell copies of the Software,
# and to permit persons to whom the Software is furnished to do so,
# subject to the following conditions:
# 
# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.
# 
# The Software is provided "AS IS", without warranty of any kind,
# express or implied, including but not limited to the warranties of
# merchantability,  fitness for a particular purpose and
# noninfringement. In no event shall the  authors or copyright holders
# be liable for any claim, damages or other liability, whether in an
# action of contract, tort or otherwise, arising from, out of or in
# connection with the Software or the use or other dealings in the
# Software.


from bzrlib.util.bencode import bencode, bdecode, Bencached
from bzrlib.tests import TestCase

class TestBencode(TestCase):
    # tests moved from within the bencode module so they're not run on every
    # startup

    def test_bdecode(self):
        try:
            bdecode('0:0:')
            assert 0
        except ValueError:
            pass
        try:
            bdecode('ie')
            assert 0
        except ValueError:
            pass
        try:
            bdecode('i341foo382e')
            assert 0
        except ValueError:
            pass
        assert bdecode('i4e') == 4L
        assert bdecode('i0e') == 0L
        assert bdecode('i123456789e') == 123456789L
        assert bdecode('i-10e') == -10L
        try:
            bdecode('i-0e')
            assert 0
        except ValueError:
            pass
        try:
            bdecode('i123')
            assert 0
        except ValueError:
            pass
        try:
            bdecode('')
            assert 0
        except ValueError:
            pass
        try:
            bdecode('i6easd')
            assert 0
        except ValueError:
            pass
        try:
            bdecode('35208734823ljdahflajhdf')
            assert 0
        except ValueError:
            pass
        try:
            bdecode('2:abfdjslhfld')
            assert 0
        except ValueError:
            pass
        assert bdecode('0:') == ''
        assert bdecode('3:abc') == 'abc'
        assert bdecode('10:1234567890') == '1234567890'
        try:
            bdecode('02:xy')
            assert 0
        except ValueError:
            pass
        try:
            bdecode('l')
            assert 0
        except ValueError:
            pass
        assert bdecode('le') == []
        try:
            bdecode('leanfdldjfh')
            assert 0
        except ValueError:
            pass
        assert bdecode('l0:0:0:e') == ['', '', '']
        try:
            bdecode('relwjhrlewjh')
            assert 0
        except ValueError:
            pass
        assert bdecode('li1ei2ei3ee') == [1, 2, 3]
        assert bdecode('l3:asd2:xye') == ['asd', 'xy']
        assert bdecode('ll5:Alice3:Bobeli2ei3eee') == [['Alice', 'Bob'], [2, 3]]
        try:
            bdecode('d')
            assert 0
        except ValueError:
            pass
        try:
            bdecode('defoobar')
            assert 0
        except ValueError:
            pass
        assert bdecode('de') == {}
        assert bdecode('d3:agei25e4:eyes4:bluee') == {'age': 25, 'eyes': 'blue'}
        assert bdecode('d8:spam.mp3d6:author5:Alice6:lengthi100000eee') == {'spam.mp3': {'author': 'Alice', 'length': 100000}}
        try:
            bdecode('d3:fooe')
            assert 0
        except ValueError:
            pass
        try:
            bdecode('di1e0:e')
            assert 0
        except ValueError:
            pass
        try:
            bdecode('d1:b0:1:a0:e')
            assert 0
        except ValueError:
            pass
        try:
            bdecode('d1:a0:1:a0:e')
            assert 0
        except ValueError:
            pass
        try:
            bdecode('i03e')
            assert 0
        except ValueError:
            pass
        try:
            bdecode('l01:ae')
            assert 0
        except ValueError:
            pass
        try:
            bdecode('9999:x')
            assert 0
        except ValueError:
            pass
        try:
            bdecode('l0:')
            assert 0
        except ValueError:
            pass
        try:
            bdecode('d0:0:')
            assert 0
        except ValueError:
            pass
        try:
            bdecode('d0:')
            assert 0
        except ValueError:
            pass
        try:
            bdecode('00:')
            assert 0
        except ValueError:
            pass
        try:
            bdecode('l-3:e')
            assert 0
        except ValueError:
            pass
        try:
            bdecode('i-03e')
            assert 0
        except ValueError:
            pass
        bdecode('d0:i3ee')


    def test_bencode(self):
        assert bencode(4) == 'i4e'
        assert bencode(0) == 'i0e'
        assert bencode(-10) == 'i-10e'
        assert bencode(12345678901234567890L) == 'i12345678901234567890e'
        assert bencode('') == '0:'
        assert bencode('abc') == '3:abc'
        assert bencode('1234567890') == '10:1234567890'
        assert bencode([]) == 'le'
        assert bencode([1, 2, 3]) == 'li1ei2ei3ee'
        assert bencode([['Alice', 'Bob'], [2, 3]]) == 'll5:Alice3:Bobeli2ei3eee'
        assert bencode({}) == 'de'
        assert bencode({'age': 25, 'eyes': 'blue'}) == 'd3:agei25e4:eyes4:bluee'
        assert bencode({'spam.mp3': {'author': 'Alice', 'length': 100000}}) == 'd8:spam.mp3d6:author5:Alice6:lengthi100000eee'
        assert bencode(Bencached(bencode(3))) == 'i3e'
        try:
            bencode({1: 'foo'})
        except TypeError:
            return
        assert 0

