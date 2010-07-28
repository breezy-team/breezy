export DARCS_EMAIL="user@example.com"
export GIT_PAGER=cat
export PATH="$(pwd)/..:$PATH"
pypath="/$(python -c 'from distutils import sysconfig; print sysconfig.get_python_lib()[1:]')/"

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

_drrecamend()
{
	echo y |darcs amend-rec --ignore-times -a
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
	mkdir dir dir2
	darcs add dir
	darcs add dir2
	_drrec -a -m "add empty dirs"
	darcs mv dir dir-p
	darcs mv dir2 dir2-p
	_drrec -a -m "rename empty dirs"
	echo a > a
	echo b > b
	darcs add a b
	_drrec -a -m "add a b"
	rm b
	_drrec -a -m "remove and rename"
	darcs mv a b
	_drrecamend
	echo c > c
	darcs add c
	# empty commit message
	_drrec -a -m ""
	cd ..
}

create_bzr()
{
	rm -rf $1
	mkdir -p $1
	cd $1
	bzr init $2
	echo A > file
	bzr add file
	bzr commit -m A
	cd ..
	rm -rf $1.tmp
	bzr branch $1 $1.tmp
	cd $1
	echo B > file
	bzr commit -m B
	cd ../$1.tmp
	echo C > file
	bzr commit -m C
	cd ../$1
	bzr merge ../$1.tmp
	echo D > file
	bzr resolve file
	echo "first line
second line
third line" | bzr commit -F /dev/stdin
	bzr tag 1.0
	echo e > file
	bzr commit -m e
	#echo f > file
	#bzr commit --author="ιαυϋ <$DARCS_EMAIL>" -m f
	#echo g > file
	#_drrec --author="" -a -m g
	cp ../data/hungarian.gif .
	bzr add hungarian.gif
	bzr commit -m "add a binary file"
	rm file
	echo test > file2
	bzr add file2
	bzr commit -m "replace file with file2"
	touch file3
	bzr add file3
	bzr commit -m "add empty file"
	rm file3
	bzr commit -m "remove file"
	cd ..
}

create_hg()
{
	rm -rf $1
	mkdir -p $1
	cd $1
	hg init $2
	echo A > file
	hg add file
	hg commit -m A
	cd ..
	rm -rf $1.tmp
	hg clone $1 $1.tmp
	cd $1
	echo B > file
	hg commit -m B
	cd ../$1.tmp
	echo C > file
	hg commit -m C
	cd ../$1
	hg pull ../$1.tmp
	hg merge
	echo D > file
	hg resolve -m file
	echo "first line
second line
third line" | hg commit -l /dev/stdin
	hg tag 1.0
	echo e > file
	hg commit -m e
	#echo f > file
	#bzr commit --author="ιαυϋ <$DARCS_EMAIL>" -m f
	#echo g > file
	#_drrec --author="" -a -m g
	cp ../data/hungarian.gif .
	hg add hungarian.gif
	hg commit -m "add a binary file"
	hg rm file
	echo test > file2
	hg add file2
	hg commit -m "replace file with file2"
	touch file3
	hg add file3
	hg commit -m "add empty file"
	hg rm file3
	hg commit -m "remove file"
	mkdir subdir
	echo test > subdir/file
	hg add subdir/file
	hg commit -m "add subdir file"
	echo test2 > subdir/file
	hg commit -m "commit with weird date" -d "Fri Apr 03 12:38:26 2009 +1300"
	cd ..
}
create_git()
{
	rm -rf $1
	mkdir -p $1
	cd $1
	git init $2
	git commit --allow-empty -m 'root commit'
	echo A > file
	git add file
	git commit -a -m A
	echo B > file
	git commit -a -m B
	git checkout -b tmp HEAD~1
	echo C > file
	git commit -a -m C
	git checkout master
	git merge tmp
	echo D > file
	echo "first line
second line
third line" | git commit -a -F -
	git branch -d tmp
	git tag 1.0
	echo e > file
	git commit -a -m e
	echo f > file
	git config i18n.commitencoding ISO-8859-2
	git commit --author="ιαυϋ <$DARCS_EMAIL>" -a -m f
	cp ../data/hungarian.gif .
	git add hungarian.gif
	git commit -a -m "add a binary file"
	rm file
	echo test > file2
	git add file2
	git commit -a -m "replace file with file2"
	touch file3
	git add file3
	git commit -a -m "add empty file"
	rm file3
	git commit -a -m "remove file"
	# now add back 'file' with its old conents, so the mark gets
	# reused
	echo f > file
	git add file
	git commit -a -m "file: other -> f"
	# this is a boring file for Darcs
	touch foo.pyc
	git add foo.pyc
	git commit -a -m "boring file"
	# replace an uppercase file to a lowercase one
	echo SPAM > SPAM
	git add SPAM
	git commit -a -m SPAM
	rm SPAM
	echo spam > spam
	git add spam
	git commit -a -m "SPAM -> spam"
	cd ..
}

diff_git()
{
	rm -rf $1.git.nonbare
	git clone -q $1.git $1.git.nonbare
	diff --exclude _darcs --exclude .git --exclude '*-darcs-backup*' -Nur $1.git.nonbare $1
	return $?
}

diff_importgit()
{
	test -z "`(cd $1.darcs; darcs diff)`" &&
	diff --exclude _darcs --exclude .git --exclude '*-darcs-backup*' -Nur $1 $1.darcs
	return $?
}

diff_importhg()
{
	cd $1.darcs && test -z "`darcs diff 2>&1`" && cd .. &&
	diff --exclude _darcs --exclude .hg --exclude '*-darcs-backup*' --exclude 'hg-export.*' \
		--exclude '.hgtags' --exclude '*.orig' -Nur $1 $1.darcs
	return $?
}

diff_importdarcs()
{
	cd $1.importdarcs && test -z "`darcs diff 2>&1`" && cd .. &&
	diff --exclude _darcs --exclude '*-darcs-backup*' -Nur $1 $2
	return $?
}

diff_importbzr()
{
	cd $1.darcs && test -z "`darcs diff 2>&1`" && cd .. &&
	diff --exclude _darcs --exclude .bzr --exclude '*-darcs-backup*' -Nur $1 $1.darcs
	return $?
}

diff_bzr()
{
	cd $1.bzr/trunk
	bzr update
	cd - >/dev/null
	diff --exclude _darcs --exclude .bzr --exclude '*-darcs-backup*' -Nur $1.bzr/trunk $1
	return $?
}

diff_hg()
{
	hg -R $1.hg update
	diff --exclude _darcs --exclude .hg --exclude '*-darcs-backup*' -Nur $1.hg $1
	return $?
}

die()
{
	echo "fatal: $@"
	exit 1
}

upd_file_darcs()
{
	cd $1
	echo $3 > $2
	_drrec -a -m "updated '$2' to '$3'"
	cd ..
}

upd_file_git()
{
	cd $1
	echo $3 > $2
	git commit -a -m "updated '$2' to '$3'"
	cd ..
}

upd_file_bzr()
{
	cd $1
	echo $3 > $2
	bzr commit -m "updated '$2' to '$3'"
	cd ..
}

upd_file_hg()
{
	cd $1
	echo $3 > $2
	hg commit -m "updated '$2' to '$3'"
	cd ..
}
