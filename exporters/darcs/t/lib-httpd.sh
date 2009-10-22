#!/bin/sh
#
# This is based on git's t/lib-httpd.sh, which is
# Copyright (c) 2008 Clemens Buchacher <drizzd@aon.at>
#

if test -n "$DFE_TEST_SKIP_HTTPD"
then
	echo "skipping test (undef DFE_TEST_SKIP_HTTPD to enable)"
	exit
fi

LIB_HTTPD_PATH=${LIB_HTTPD_PATH-'/usr/sbin/httpd'}
LIB_HTTPD_PORT=${LIB_HTTPD_PORT-'8111'}

HTTPD_ROOT_PATH="$PWD"/httpd
HTTPD_DOCUMENT_ROOT_PATH=$HTTPD_ROOT_PATH/www

if ! test -x "$LIB_HTTPD_PATH"
then
        echo "skipping test, no web server found at '$LIB_HTTPD_PATH'"
        exit
fi

HTTPD_VERSION=`$LIB_HTTPD_PATH -v | \
	sed -n 's/^Server version: Apache\/\([0-9]*\)\..*$/\1/p; q'`

if test -n "$HTTPD_VERSION"
then
	if test -z "$LIB_HTTPD_MODULE_PATH"
	then
		if ! test $HTTPD_VERSION -ge 2
		then
			echo "skipping test, at least Apache version 2 is required"
			exit
		fi

		LIB_HTTPD_MODULE_PATH='/usr/lib/apache'
	fi
else
	error "Could not identify web server at '$LIB_HTTPD_PATH'"
fi

HTTPD_PARA="-d $HTTPD_ROOT_PATH -f $HTTPD_ROOT_PATH/apache.conf"

prepare_httpd() {
	mkdir -p $HTTPD_DOCUMENT_ROOT_PATH

	ln -s $LIB_HTTPD_MODULE_PATH $HTTPD_ROOT_PATH/modules

	echo "PidFile httpd.pid" > $HTTPD_ROOT_PATH/apache.conf
	echo "DocumentRoot www" >> $HTTPD_ROOT_PATH/apache.conf
	echo "ErrorLog error.log" >> $HTTPD_ROOT_PATH/apache.conf

	HTTPD_URL=http://127.0.0.1:$LIB_HTTPD_PORT
}

start_httpd() {
	prepare_httpd

	"$LIB_HTTPD_PATH" $HTTPD_PARA \
		-c "Listen 127.0.0.1:$LIB_HTTPD_PORT" -k start
}

stop_httpd() {
	"$LIB_HTTPD_PATH" $HTTPD_PARA -k stop
}
