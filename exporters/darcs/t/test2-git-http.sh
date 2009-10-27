. ./lib.sh
. ./lib-httpd.sh

rm -rf test2.darcs test2.git httpd
create_darcs test2 --darcs-2
mkdir -p $HTTPD_DOCUMENT_ROOT_PATH
mv -v test2 $HTTPD_DOCUMENT_ROOT_PATH
ln -s $HTTPD_DOCUMENT_ROOT_PATH/test2 .

mkdir test2.git
cd test2.git
git --bare init
cd ..
start_httpd
darcs-fast-export $HTTPD_URL/test2 |(cd test2.git; git fast-import)
ret=$?
stop_httpd
if [ $ret != 0 ]; then
	exit $ret
fi
diff_git test2
exit $?
