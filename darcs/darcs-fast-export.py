#!/usr/bin/env python

import xml.dom.minidom
import xml.parsers.expat
import os
import sys
import gzip
import time
import shutil

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
	if not ">" in author:
		author = "%s <%s>" % (author.split('@')[0], author)
	return author.encode('utf-8')

def progress(s):
	print "progress [%s] %s" % (time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()), s)
	sys.stdout.flush()

origin = os.path.abspath(sys.argv[1])
working = "%s.darcs" % origin

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
os.system("darcs init --old-fashioned-inventory")

patches = xmldoc.getElementsByTagName('patch')
# this may be huge and we need it many times
patchnum = len(patches)

count = 0
for i in patches:
	# apply the patch
	buf = ["\nNew patches:\n"]
	sock = gzip.open("%s/_darcs/patches/%s" % (origin, i.attributes['hash'].value))
	buf.append(sock.read())
	sock.close()
	sock = os.popen("darcs changes --context")
	buf.append(sock.read())
	sock.close()
	sock = os.popen("darcs apply --allow-conflicts >/dev/null", "w")
	sock.write("".join(buf))
	sock.close()
	message = get_patchname(i)
	# export the commit
	print "commit refs/heads/master"
	print "mark :%s" % count
	date = int(time.mktime(time.strptime(i.attributes['date'].value, "%Y%m%d%H%M%S"))) + get_zone_int()
	print "committer %s %s %s" % (get_author(i), date, get_zone_str())
	print "data %d\n%s" % (len(message), message)
	# export the files
	print "deleteall"
	for (root, dirs, files) in os.walk ("."):
		for f in files:
			j = os.path.normpath(os.path.join(root, f))
			if j.startswith("_darcs") or "-darcs-backup" in j:
				continue
			sock = open(j)
			buf = sock.read()
			sock.close()
			# fixme
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

os.chdir(cwd)
shutil.rmtree(working)
