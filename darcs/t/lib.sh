export DARCS_EMAIL="user@example.com"

_drrec()
{
	darcs rec --ignore-times "$@"
}

_drrec_multiline()
{
	echo -e "`LANG= LC_ALL= date +"%a %b %d %H:%M:%S %Z %Y"`
$DARCS_EMAIL
$@" | darcs rec --ignore-times -a --pipe .
}

create_darcs()
{
	rm -rf $1
	mkdir -p $1
	cd $1
	darcs init $2
	echo A > file
	darcs add file
	_drrec -a -m A
	cd ..
	rm -rf $1.tmp
	darcs get $1 $1.tmp
	cd $1
	echo B > file
	_drrec -a -m B
	cd ../$1.tmp
	echo C > file
	_drrec -a -m C
	cd ../$1
	darcs pull -a ../$1.tmp
	echo D > file
	_drrec_multiline "first line
second line
third line"
	darcs tag 1.0
	echo e > file
	_drrec -a -m e
	echo f > file
	_drrec --author="ιαυϋ <$DARCS_EMAIL>" -a -m f
	echo g > file
	_drrec --author="" -a -m g
	cp ../data/hungarian.gif .
	darcs add hungarian.gif
	_drrec -a -m "add a binary file"
	rm file
	echo test > file2
	darcs add file2
	_drrec -a -m "replace file with file2"
	touch file3
	darcs add file3
	_drrec -a -m "add empty file"
	rm file3
	_drrec -a -m "remove file"
	cd ..
}

diff_git()
{
	rm -rf $1.git.nonbare
	git clone -q $1.git $1.git.nonbare
	diff --exclude _darcs --exclude .git --exclude '*-darcs-backup*' -Naur $1.git.nonbare $1
	return $?
}
