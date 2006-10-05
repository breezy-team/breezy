# Copyright (C) 2006 Canonical Ltd
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


def send_changeset(branch, revisions, to_address, message, file):
    import bzrlib.osutils
    from bzrlib import find_branch
    from bzrlib.commands import BzrCommandError
    import gen_changeset
    import send_changeset
    from cStringIO import StringIO

    base_rev_id, target_rev_id = common.canonicalize_revision(branch, revisions)
    rev = branch.get_revision(target_rev_id)
    if not message:
        message = rev.message.split('\n')[0]

    from_address = bzrlib.osutils._get_user_id()

    outer = MIMEMultipart()
    outer['Subject'] = '[PATCH] ' + message
    outer['To'] = to_address
    outer['From'] = from_address

    # Either read the mail body from the specified file, or spawn
    # an editor and let the user type a description.
    if file:
        mail_body = open(file, "U").read()
    else:
        info = "Changeset by %s\n" % rev.committer
        info += "From %s\n" % base_rev_id
        info += "with the following message:\n"
        for line in rev.message.split('\n'):
            info += "  " + line + "\n"

        mail_body = bzrlib.osutils.get_text_message(info)
        if mail_body is None:
            raise BzrCommandError("aborted")
    outer.attach(MIMEText(mail_body))
    
    changeset_fp = StringIO()
    gen_changeset.show_changeset(branch, revisions, to_file=changeset_fp)
    outer.attach(MIMEText(changeset_fp.getvalue()))

    try:
        fp = open(os.path.join(bzrlib.osutils.config_dir(), 'smtp-host'), 'U')
        smtpconn = smtplib.SMTP(fp.readline().strip('\n'))
    except:
        smtpconn = smtplib.SMTP()

    smtpconn.connect()
    smtpconn.sendmail(from_address, to_address, outer.as_string())
    smtpconn.close()
