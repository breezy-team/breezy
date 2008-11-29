#!/bin/sh

create_config()
{
	cd $1
	mypath=$(pwd)
	cd - >/dev/null
	myname=$(basename $mypath)

	cat > config << EOF
[DEFAULT]
encoding-errors-policy = replace

[$myname]
source = darcs:$myname
target = git:$myname

[darcs:$myname]
subdir = darcs
repository = $mypath

[git:$myname]
subdir = git
repository = $mypath.git
EOF
}

PATH=$HOME/darcs/tailor:$PATH
if [ ! -d darcs-benchmark ]; then
	darcs get http://code.haskell.org/darcs/darcs-benchmark
	cd darcs-benchmark
else
	cd darcs-benchmark
	darcs pull -a
fi
sh initialise.sh
cd big-zoo
if [ -n "$1" ]; then
	targets=$1
else
	targets=*_play.tar.gz
fi
for i in $targets
do
	echo "benchmarking $i"
	rm -rf _playground
	tar xf $i
	cd _playground
	log="../$i.tailor-$(tailor --version).log"
	create_config sandbox
	sh -c 'time tailor --configfile config' 2>&1 |tee $log
	if diff --exclude _darcs --exclude .git -Nur sandbox git >/dev/null; then
		echo "ok, the result is correct" >> $log
	else
		echo "ouch, the result is corrupted" >> $log
		exit 1
	fi
	cd ..
done
