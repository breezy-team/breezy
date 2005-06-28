#!/usr/bin/env python
"""\
Generate a changeset and send it by mail.
"""

import bzrlib, bzrlib.changeset
import common, smtplib

from email import Encoders
from email.Message import Message
from email.MIMEBase import MIMEBase
from email.MIMEMultipart import MIMEMultipart
from email.MIMEText import MIMEText


def send_changeset(to_address, from_address, subject, 
                   changeset_fp, message):
    # Create the enclosing (outer) message
    outer = MIMEMultipart()
    outer['Subject'] = '[PATCH] ' + subject
    outer['To'] = to_address
    outer['From'] = from_address

    if message:
        msg = MIMEText(message)
        outer.attach(msg)

    msg = MIMEText(changeset_fp.read())
    #msg.add_header('Content-Disposition', 'attachment', filename=')

    outer.attach(msg)

    s = smtplib.SMTP()
    s.connect()
    s.sendmail(from_address, to_address, outer.as_string())
    s.close()
    
