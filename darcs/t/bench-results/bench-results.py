from glob import glob
import re

def cmp_data(a, b):
	return cmp(a[0], b[0])

logs = glob("../darcs-benchmark/big-zoo/*.log")

data = []

for i in logs:
	sock = open(i)
	for j in sock.readlines():
		if "Num Patches:" in j:
			patches = int(j.split(": ")[1].strip())
		elif j.startswith("real"):
			l = re.sub("real\t([0-9]+)m([0-9.]+)s\n", r"\1 \2", j).split(" ")
			secs = int(l[0])*60 + float(l[1])
			hours = secs / 3600
	data.append([patches, hours])
data.sort(cmp=cmp_data)
for i in data:
	print "%s %s" % (i[0], i[1])
