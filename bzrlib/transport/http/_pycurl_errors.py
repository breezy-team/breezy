# Copyright (C) 2006 Canonical
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

# Taken from curl/curl.h
CURLE_OK = 0
CURLE_UNSUPPORTED_PROTOCOL = 1
CURLE_FAILED_INIT = 2
CURLE_URL_MALFORMAT = 3
CURLE_URL_MALFORMAT_USER = 4 # (NOT USED)
CURLE_COULDNT_RESOLVE_PROXY = 5
CURLE_COULDNT_RESOLVE_HOST = 6
CURLE_COULDNT_CONNECT = 7
CURLE_FTP_WEIRD_SERVER_REPLY = 8
CURLE_FTP_ACCESS_DENIED = 9 # a service was denied by the FTP server
                            # due to lack of access - when login fails
                            # this is not returned.
CURLE_FTP_USER_PASSWORD_INCORRECT = 10
CURLE_FTP_WEIRD_PASS_REPLY = 11
CURLE_FTP_WEIRD_USER_REPLY = 12
CURLE_FTP_WEIRD_PASV_REPLY = 13
CURLE_FTP_WEIRD_227_FORMAT = 14
CURLE_FTP_CANT_GET_HOST = 15
CURLE_FTP_CANT_RECONNECT = 16
CURLE_FTP_COULDNT_SET_BINARY = 17
CURLE_PARTIAL_FILE = 18
CURLE_FTP_COULDNT_RETR_FILE = 19
CURLE_FTP_WRITE_ERROR = 20
CURLE_FTP_QUOTE_ERROR = 21
CURLE_HTTP_RETURNED_ERROR = 22
CURLE_WRITE_ERROR = 23
CURLE_MALFORMAT_USER = 24 # NOT USED
CURLE_FTP_COULDNT_STOR_FILE = 25 # failed FTP upload
CURLE_READ_ERROR = 26 # could open/read from file
CURLE_OUT_OF_MEMORY = 27
CURLE_OPERATION_TIMEOUTED = 28 # the timeout time was reached
CURLE_FTP_COULDNT_SET_ASCII = 29 # TYPE A failed
CURLE_FTP_PORT_FAILED = 30 # FTP PORT operation failed
CURLE_FTP_COULDNT_USE_REST = 31 # the REST command failed
CURLE_FTP_COULDNT_GET_SIZE = 32 # the SIZE command failed
CURLE_HTTP_RANGE_ERROR = 33 # RANGE "command" didn't work
CURLE_HTTP_POST_ERROR = 34
CURLE_SSL_CONNECT_ERROR = 35 # wrong when connecting with SSL
CURLE_BAD_DOWNLOAD_RESUME = 36 # couldn't resume download
CURLE_FILE_COULDNT_READ_FILE = 37
CURLE_LDAP_CANNOT_BIND = 38
CURLE_LDAP_SEARCH_FAILED = 39
CURLE_LIBRARY_NOT_FOUND = 40
CURLE_FUNCTION_NOT_FOUND = 41
CURLE_ABORTED_BY_CALLBACK = 42
CURLE_BAD_FUNCTION_ARGUMENT = 43
CURLE_BAD_CALLING_ORDER = 44 # NOT USED
CURLE_INTERFACE_FAILED = 45 # CURLOPT_INTERFACE failed
CURLE_BAD_PASSWORD_ENTERED = 46 # NOT USED
CURLE_TOO_MANY_REDIRECTS  = 47 # catch endless re-direct loops
CURLE_UNKNOWN_TELNET_OPTION = 48 # User specified an unknown option
CURLE_TELNET_OPTION_SYNTAX  = 49 # Malformed telnet option
CURLE_OBSOLETE = 50 # NOT USED
CURLE_SSL_PEER_CERTIFICATE = 51 # peer's certificate wasn't ok
CURLE_GOT_NOTHING = 52 # when this is a specific error
CURLE_SSL_ENGINE_NOTFOUND = 53 # SSL crypto engine not found
CURLE_SSL_ENGINE_SETFAILED = 54 # can not set SSL crypto engine as default
CURLE_SEND_ERROR = 55 # failed sending network data
CURLE_RECV_ERROR = 56 # failure in receiving network data
CURLE_SHARE_IN_USE = 57 # share is in use
CURLE_SSL_CERTPROBLEM = 58 # problem with the local certificate
CURLE_SSL_CIPHER = 59 # couldn't use specified cipher
CURLE_SSL_CACERT = 60 # problem with the CA cert (path?)
CURLE_BAD_CONTENT_ENCODING = 61 # Unrecognized transfer encoding
CURLE_LDAP_INVALID_URL = 62 # Invalid LDAP URL
CURLE_FILESIZE_EXCEEDED = 63 # Maximum file size exceeded
CURLE_FTP_SSL_FAILED = 64 # Requested FTP SSL level failed
CURLE_SEND_FAIL_REWIND = 65 # Sending the data requires a rewind that failed
CURLE_SSL_ENGINE_INITFAILED = 66 # failed to initialise ENGINE
CURLE_LOGIN_DENIED = 67 # user, password or similar was not
                        # accepted and we failed to login
CURLE_TFTP_NOTFOUND = 68 # file not found on server
CURLE_TFTP_PERM = 69 # permission problem on server
CURLE_TFTP_DISKFULL = 70 # out of disk space on server
CURLE_TFTP_ILLEGAL = 71 # Illegal TFTP operation
CURLE_TFTP_UNKNOWNID = 72 # Unknown transfer ID
CURLE_TFTP_EXISTS = 73 # File already exists
CURLE_TFTP_NOSUCHUSER = 74 # No such user


# Create the reverse mapping, so we can look things up.
errorcode = {}
for name, val in globals().items():
    if name.startswith('CURLE'):
        errorcode[val] = name
