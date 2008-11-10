#!/usr/bin/env python

"""

    darcs-fast-export.py - darcs backend for fast data importers

    Copyright (c) 2008 Miklos Vajna <vmiklos@frugalware.org>

    This program is free software; you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation; either version 2, or (at your option)
    any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program; if not, write to the Free Software
    Foundation, Inc., 675 Mass Ave, Cambridge, MA 02139, USA.

"""

import xml.dom.minidom
import xml.parsers.expat
import os
import sys
import gzip
import time
import shutil
import popen2

sys = reload(sys)
sys.setdefaultencoding("utf-8")

def __get_zone():
	now = time.localtime()
	if time.daylight and now[-1]:
		offset = time.altzone
	else:
		offset = time.timezone
	hours, minutes = divmod(abs(offset), 3600)
	if offset > 0:
		sign = "-"
	else:
		sign = "+"
	return sign, hours, minutes

def get_zone_str():
	sign, hours, minutes = __get_zone()
	return "%s%02d%02d" % (sign, hours, minutes // 60)

def get_zone_int():
	sign, hours, minutes = __get_zone()
	ret = hours*3600+minutes*60
	if sign == "-":
		ret *= -1
	return ret

def get_patchname(patch):
	ret = []
	if patch.attributes['inverted'] == 'True':
		ret.append("UNDO: ")
	ret.append(i.getElementsByTagName("name")[0].childNodes[0].data)
	lines = i.getElementsByTagName("comment")
	if lines:
		ret.extend(["\n", lines[0].childNodes[0].data])
	return "".join(ret).encode('utf-8')

def get_author(patch):
	author = patch.attributes['author'].value
	if not len(author):
		author = "darcs-fast-export <darcs-fast-export>"
	elif not ">" in author:
		author = "%s <%s>" % (author.split('@')[0], author)
	return author.encode('utf-8')

def progress(s):
	print "progress [%s] %s" % (time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()), s)
	sys.stdout.flush()

def log(s):
	logsock.write("[%s] %s" % (time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()), s))

origin = os.path.abspath(sys.argv[1])
working = "%s.darcs" % origin
patchfile = "%s.patch" % origin
logfile = "%s.log" % origin
logsock = open(logfile, "w")

progress("getting list of patches")
sock = os.popen("darcs changes --xml --reverse --repo %s" % origin)
buf = sock.read()
# this is hackish. we need to escape some bad chars, otherwise the xml
# will not be valid
buf = buf.replace('\x1b', '^]')
sock.close()
try:
	xmldoc = xml.dom.minidom.parseString(buf)
except xml.parsers.expat.ExpatError:
	import chardet
	progress("encoding is not utf8, guessing charset")
	encoding = chardet.detect(buf)['encoding']
	progress("detected encoding is %s" % encoding)
	xmldoc = xml.dom.minidom.parseString(unicode(buf, encoding).encode('utf-8'))
sys.stdout.flush()

# init the tmp darcs repo
os.mkdir(working)
cwd = os.getcwd()
os.chdir(working)
darcs2 = True
if os.path.exists(os.path.join(origin, "_darcs", "pristine")):
	darcs2 = False
if darcs2:
	os.system("darcs init --darcs-2")
else:
	os.system("darcs init --old-fashioned-inventory")

patches = xmldoc.getElementsByTagName('patch')
# this may be huge and we need it many times
patchnum = len(patches)

count = 1
paths = []
for i in patches:
	# apply the patch
	hash = i.attributes['hash'].value
	if not darcs2:
		buf = ["\nNew patches:\n"]
		sock = gzip.open(os.path.join(origin, "_darcs", "patches", hash))
		buf.append(sock.read())
		sock.close()
		sock = os.popen("darcs changes --context")
		buf.append(sock.read())
		sock.close()
		pout, pin = popen2.popen2("darcs apply --allow-conflicts")
		pin.write("".join(buf))
		pin.close()
		log("Applying %s:\n%s" % (hash, pout.read()))
		pout.close()
	else:
		os.chdir(origin)
		sock = os.popen("darcs send -a -o %s --matches='hash %s' %s" % (patchfile, hash, working))
		log("Extracting %s:\n%s" % (hash, sock.read()))
		sock.close()
		os.chdir(working)
		sock = os.popen("darcs apply --allow-conflicts < %s" % patchfile)
		log("Applying %s:\n%s" % (hash, sock.read()))
		sock.close()
	message = get_patchname(i)
	# export the commit
	print "commit refs/heads/master"
	print "mark :%s" % count
	date = int(time.mktime(time.strptime(i.attributes['date'].value, "%Y%m%d%H%M%S"))) + get_zone_int()
	print "committer %s %s %s" % (get_author(i), date, get_zone_str())
	print "data %d\n%s" % (len(message), message)
	# export the files
	for j in paths:
		print "D %s" % j
	paths = []
	for (root, dirs, files) in os.walk ("."):
		for f in files:
			j = os.path.normpath(os.path.join(root, f))
			if j.startswith("_darcs") or "-darcs-backup" in j:
				continue
			paths.append(j)
			sock = open(j)
			buf = sock.read()
			sock.close()
			# darcs does not track the executable bit :/
			print "M 644 inline %s" % j
			print "data %s\n%s" % (len(buf), buf)
	if message[:4] == "TAG ":
		print "tag %s" % message[4:]
		print "from :%s" % count
		print "tagger %s %s %s" % (get_author(i), date, get_zone_str())
		print "data %d\n%s" % (len(message[4:]), message[4:])
	if count % 1000 == 0:
		progress("%d/%d patches" % (count, patchnum))
	count += 1

shutil.rmtree(working)
logsock.close()
