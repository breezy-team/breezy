"""
Based on this original script: http://www.kirbyfooty.com/simplemapi.py

Now works (and tested) with:
    Outlook Express, Outlook 97 and 2000, 
    Eudora, Incredimail and Mozilla Thunderbird (1.5.0.2)

Date   : 30 May 2006
Version: 1.0.0

John Popplewell
john@johnnypops.demon.co.uk
http://www.johnnypops.demon.co.uk/python/

Thanks to Werner F. Bruhin and Michele Petrazzo on the ctypes list.
"""

import os
from ctypes import *

FLAGS = c_ulong
LHANDLE = c_ulong
LPLHANDLE = POINTER(LHANDLE)

# Return codes
SUCCESS_SUCCESS = 0
MAPI_USER_ABORT = 1
# Recipient class
MAPI_ORIG       = 0
MAPI_TO         = 1
# Send flags
MAPI_LOGON_UI   = 1
MAPI_DIALOG     = 8

class MapiRecipDesc(Structure):
    _fields_ = [
        ('ulReserved',      c_ulong),
        ('ulRecipClass',    c_ulong),
        ('lpszName',        c_char_p),
        ('lpszAddress',     c_char_p),
        ('ulEIDSize',       c_ulong),
        ('lpEntryID',       c_void_p),
    ]
lpMapiRecipDesc  = POINTER(MapiRecipDesc)
lppMapiRecipDesc = POINTER(lpMapiRecipDesc)

class MapiFileDesc(Structure):
    _fields_ = [
        ('ulReserved',      c_ulong),
        ('flFlags',         c_ulong),
        ('nPosition',       c_ulong),
        ('lpszPathName',    c_char_p),
        ('lpszFileName',    c_char_p),
        ('lpFileType',      c_void_p),
    ]
lpMapiFileDesc = POINTER(MapiFileDesc)

class MapiMessage(Structure):
    _fields_ = [
        ('ulReserved',          c_ulong),
        ('lpszSubject',         c_char_p),
        ('lpszNoteText',        c_char_p),
        ('lpszMessageType',     c_char_p),
        ('lpszDateReceived',    c_char_p),
        ('lpszConversationID',  c_char_p),
        ('flFlags',             FLAGS),
        ('lpOriginator',        lpMapiRecipDesc),
        ('nRecipCount',         c_ulong),
        ('lpRecips',            lpMapiRecipDesc),
        ('nFileCount',          c_ulong),
        ('lpFiles',             lpMapiFileDesc),
    ]
lpMapiMessage = POINTER(MapiMessage)

MAPI                    = windll.mapi32
MAPISendMail            = MAPI.MAPISendMail
MAPISendMail.restype    = c_ulong
MAPISendMail.argtypes   = (LHANDLE, c_ulong, lpMapiMessage, FLAGS, c_ulong)

MAPIResolveName         = MAPI.MAPIResolveName
MAPIResolveName.restype = c_ulong
MAPIResolveName.argtypes= (LHANDLE, c_ulong, c_char_p, FLAGS, c_ulong, lppMapiRecipDesc)

MAPIFreeBuffer          = MAPI.MAPIFreeBuffer
MAPIFreeBuffer.restype  = c_ulong
MAPIFreeBuffer.argtypes = (c_void_p, )

MAPILogon               = MAPI.MAPILogon
MAPILogon.restype       = c_ulong
MAPILogon.argtypes      = (LHANDLE, c_char_p, c_char_p, FLAGS, c_ulong, LPLHANDLE)

MAPILogoff              = MAPI.MAPILogoff
MAPILogoff.restype      = c_ulong
MAPILogoff.argtypes     = (LHANDLE, c_ulong, FLAGS, c_ulong)


def _logon(profileName=None, password=None):
    pSession = LHANDLE()
    rc = MAPILogon(0, profileName, password, MAPI_LOGON_UI, 0, byref(pSession))
    if rc != SUCCESS_SUCCESS:
        raise WindowsError, "MAPI error %i" % rc
    return pSession


def _logoff(session):
    rc = MAPILogoff(session, 0, 0, 0)
    if rc != SUCCESS_SUCCESS:
        raise WindowsError, "MAPI error %i" % rc


def _resolveName(session, name):
    pRecipDesc = lpMapiRecipDesc()
    rc = MAPIResolveName(session, 0, name, 0, 0, byref(pRecipDesc))
    if rc != SUCCESS_SUCCESS:
        raise WindowsError, "MAPI error %i" % rc
    rd = pRecipDesc.contents
    name, address = rd.lpszName, rd.lpszAddress
    rc = MAPIFreeBuffer(pRecipDesc)
    if rc != SUCCESS_SUCCESS:
        raise WindowsError, "MAPI error %i" % rc
    return name, address


def _sendMail(session, recipient, subject, body, attach):
    nFileCount = len(attach)
    if attach: 
        MapiFileDesc_A = MapiFileDesc * len(attach) 
        fda = MapiFileDesc_A() 
        for fd, fa in zip(fda, attach): 
            fd.ulReserved = 0 
            fd.flFlags = 0 
            fd.nPosition = -1 
            fd.lpszPathName = fa 
            fd.lpszFileName = None 
            fd.lpFileType = None 
        lpFiles = fda
    else:
        lpFiles = lpMapiFileDesc()

    RecipWork = recipient.split(';')
    RecipCnt = len(RecipWork)
    MapiRecipDesc_A = MapiRecipDesc * len(RecipWork) 
    rda = MapiRecipDesc_A() 
    for rd, ra in zip(rda, RecipWork):
        rd.ulReserved = 0 
        rd.ulRecipClass = MAPI_TO
        try:
            rd.lpszName, rd.lpszAddress = _resolveName(session, ra)
        except WindowsError:
            # work-round for Mozilla Thunderbird
            rd.lpszName, rd.lpszAddress = None, ra
        rd.ulEIDSize = 0
        rd.lpEntryID = None
    recip = rda

    msg = MapiMessage(0, subject, body, None, None, None, 0, lpMapiRecipDesc(),
                      RecipCnt, recip,
                      nFileCount, lpFiles)

    rc = MAPISendMail(session, 0, byref(msg), MAPI_DIALOG, 0)
    if rc != SUCCESS_SUCCESS and rc != MAPI_USER_ABORT:
        raise WindowsError, "MAPI error %i" % rc


def SendMail(recipient, subject="", body="", attachfiles=""):
    """Post an e-mail message using Simple MAPI
    
    recipient - string: address to send to (multiple addresses separated with a semicolon)
    subject   - string: subject header
    body      - string: message text
    attach    - string: files to attach (multiple attachments separated with a semicolon)
    """

    attach = []
    AttachWork = attachfiles.split(';')
    for file in AttachWork:
        if os.path.exists(file):
            attach.append(file)
    attach = map(os.path.abspath, attach)

    restore = os.getcwd()
    try:
        session = _logon()
        try:
            _sendMail(session, recipient, subject, body, attach)
        finally:
            _logoff(session)
    finally:
        os.chdir(restore)


if __name__ == '__main__':
    import sys
    recipient = "test@johnnypops.demon.co.uk"
    subject = "Test Message Subject"
    body = "Hi,\r\n\r\nthis is a quick test message,\r\n\r\ncheers,\r\nJohn."
    attachment = sys.argv[0]
    SendMail(recipient, subject, body, attachment)
