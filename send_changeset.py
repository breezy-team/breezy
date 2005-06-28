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


def send_changeset(b, revno, to_address, message, file, diff_options):
    from bzrlib import find_branch
    from bzrlib.commands import BzrCommandError
    import gen_changeset
    import send_changeset
    import StringIO

    revision = b.get_revision(b.lookup_revision(revno))
    if not message:
        message = revision.message.split('\n')[0]

    from_address = bzrlib.osutils._get_user_id()

    outer = MIMEMultipart()
    outer['Subject'] = '[PATCH] ' + message
    outer['To'] = to_address
    outer['From'] = from_address

    # Either read the mail body from the specified file, or spawn
    # an editor and let the user type a description.
    if file:
        mail_body = open(file, "rt").read()
    else:
        info = "Changset for revision %d by %s\n" % (revno,
                                                     revision.committer)
        info += "with the following message:\n"
        for line in revision.message.split('\n'):
            info += "  " + line + "\n"

        mail_body = bzrlib.osutils.get_text_message(info)
        if mail_body is None:
            raise BzrCommandError("aborted")
    outer.attach(MIMEText(mail_body))
    
    changeset_fp = StringIO.StringIO()
    gen_changeset.show_changeset(b, revno,
                                 external_diff_options=diff_options,
                                 to_file=changeset_fp)
    outer.attach(MIMEText(changeset_fp.getvalue()))

    try:
        fp = open(os.path.join(bzrlib.osutils.config_dir(), 'smtp-host'), 'rt')
        smtpconn = smtplib.SMTP(fp.readline().strip('\n'))
    except:
        smtpconn = smtplib.SMTP()

    smtpconn.connect()
    smtpconn.sendmail(from_address, to_address, outer.as_string())
    smtpconn.close()
