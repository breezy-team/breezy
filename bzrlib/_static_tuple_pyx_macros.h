/* Copyright (C) 2009 Canonical Ltd
 * 
 * This program is free software; you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation; either version 2 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with this program; if not, write to the Free Software
 * Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA
 */

#ifndef _STATIC_TUPLE_PYX_MACROS_H_
#define _STATIC_TUPLE_PYX_MACROS_H_

#define STATIC_TUPLE_INTERNED_FLAG 0x01
#define STATIC_TUPLE_ALL_STRING    0x02
#define StaticTuple_SET_ITEM(key, offset, val) \
    ((((StaticTuple*)(key))->items[(offset)]) = ((PyObject *)(val)))
#define StaticTuple_GET_ITEM(key, offset) (((StaticTuple*)key)->items[offset])

#endif // _STATIC_TUPLE_PYX_MACROS_H_
