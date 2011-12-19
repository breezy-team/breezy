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
# Modifications copyright (C) 2008 Canonical Ltd

from __future__ import absolute_import

class BDecoder(object):

    def __init__(self, yield_tuples=False):
        """Constructor.

        :param yield_tuples: if true, decode "l" elements as tuples rather than
            lists.
        """
        self.yield_tuples = yield_tuples
        decode_func = {}
        decode_func['l'] = self.decode_list
        decode_func['d'] = self.decode_dict
        decode_func['i'] = self.decode_int
        decode_func['0'] = self.decode_string
        decode_func['1'] = self.decode_string
        decode_func['2'] = self.decode_string
        decode_func['3'] = self.decode_string
        decode_func['4'] = self.decode_string
        decode_func['5'] = self.decode_string
        decode_func['6'] = self.decode_string
        decode_func['7'] = self.decode_string
        decode_func['8'] = self.decode_string
        decode_func['9'] = self.decode_string
        self.decode_func = decode_func

    def decode_int(self, x, f):
        f += 1
        newf = x.index('e', f)
        try:
            n = int(x[f:newf])
        except (OverflowError, ValueError):
            n = long(x[f:newf])
        if x[f] == '-':
            if x[f + 1] == '0':
                raise ValueError
        elif x[f] == '0' and newf != f+1:
            raise ValueError
        return (n, newf+1)

    def decode_string(self, x, f):
        colon = x.index(':', f)
        try:
            n = int(x[f:colon])
        except (OverflowError, ValueError):
            n = long(x[f:colon])
        if x[f] == '0' and colon != f+1:
            raise ValueError
        colon += 1
        return (x[colon:colon+n], colon+n)

    def decode_list(self, x, f):
        r, f = [], f+1
        while x[f] != 'e':
            v, f = self.decode_func[x[f]](x, f)
            r.append(v)
        if self.yield_tuples:
            r = tuple(r)
        return (r, f + 1)

    def decode_dict(self, x, f):
        r, f = {}, f+1
        lastkey = None
        while x[f] != 'e':
            k, f = self.decode_string(x, f)
            if lastkey >= k:
                raise ValueError
            lastkey = k
            r[k], f = self.decode_func[x[f]](x, f)
        return (r, f + 1)

    def bdecode(self, x):
        if type(x) != str:
            raise TypeError
        try:
            r, l = self.decode_func[x[0]](x, 0)
        except (IndexError, KeyError, OverflowError), e:
            import sys
            raise ValueError, ValueError(str(e)), sys.exc_info()[2]
        if l != len(x):
            raise ValueError
        return r


_decoder = BDecoder()
bdecode = _decoder.bdecode

_tuple_decoder = BDecoder(True)
bdecode_as_tuple = _tuple_decoder.bdecode


from types import StringType, IntType, LongType, DictType, ListType, TupleType

class Bencached(object):
    __slots__ = ['bencoded']

    def __init__(self, s):
        self.bencoded = s

def encode_bencached(x,r):
    r.append(x.bencoded)

def encode_int(x, r):
    r.extend(('i', str(x), 'e'))

def encode_string(x, r):
    r.extend((str(len(x)), ':', x))

def encode_list(x, r):
    r.append('l')
    for i in x:
        encode_func[type(i)](i, r)
    r.append('e')

def encode_dict(x,r):
    r.append('d')
    ilist = x.items()
    ilist.sort()
    for k, v in ilist:
        r.extend((str(len(k)), ':', k))
        encode_func[type(v)](v, r)
    r.append('e')

encode_func = {}
encode_func[type(Bencached(0))] = encode_bencached
encode_func[IntType] = encode_int
encode_func[LongType] = encode_int
encode_func[StringType] = encode_string
encode_func[ListType] = encode_list
encode_func[TupleType] = encode_list
encode_func[DictType] = encode_dict

try:
    from types import BooleanType
except ImportError:
    pass
else:
    def encode_bool(x,r):
        encode_int(int(x), r)
    encode_func[BooleanType] = encode_bool

from bzrlib._static_tuple_py import StaticTuple
encode_func[StaticTuple] = encode_list
try:
    from bzrlib._static_tuple_c import StaticTuple
except ImportError:
    pass
else:
    encode_func[StaticTuple] = encode_list


def bencode(x):
    r = []
    encode_func[type(x)](x, r)
    return ''.join(r)

