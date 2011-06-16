# Copyright (C) 2005, 2006, 2007, 2009, 2011 Canonical Ltd
#   Authors: Robert Collins <robert.collins@canonical.com>
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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

"""Tests for signing and verifying blobs of data via gpg."""

# import system imports here
import sys

from bzrlib import errors, ui
import bzrlib.gpg as gpg
from bzrlib.tests import TestCase

class FakeConfig(object):

    def gpg_signing_command(self):
        return "false"


class TestCommandLine(TestCase):

    def test_signing_command_line(self):
        my_gpg = gpg.GPGStrategy(FakeConfig())
        self.assertEqual(['false',  '--clearsign'],
                         my_gpg._command_line())

    def test_checks_return_code(self):
        # This test needs a unix like platform - one with 'false' to run.
        # if you have one, please make this work :)
        my_gpg = gpg.GPGStrategy(FakeConfig())
        self.assertRaises(errors.SigningFailed, my_gpg.sign, 'content')

    def assertProduces(self, content):
        # This needs a 'cat' command or similar to work.
        my_gpg = gpg.GPGStrategy(FakeConfig())
        if sys.platform == 'win32':
            # Windows doesn't come with cat, and we don't require it
            # so lets try using python instead.
            # But stupid windows and line-ending conversions.
            # It is too much work to make sys.stdout be in binary mode.
            # http://aspn.activestate.com/ASPN/Cookbook/Python/Recipe/65443
            my_gpg._command_line = lambda:[sys.executable, '-c',
                    'import sys; sys.stdout.write(sys.stdin.read())']
            new_content = content.replace('\n', '\r\n')

            self.assertEqual(new_content, my_gpg.sign(content))
        else:
            my_gpg._command_line = lambda:['cat', '-']
            self.assertEqual(content, my_gpg.sign(content))

    def test_returns_output(self):
        content = "some content\nwith newlines\n"
        self.assertProduces(content)

    def test_clears_progress(self):
        content = "some content\nwith newlines\n"
        old_clear_term = ui.ui_factory.clear_term
        clear_term_called = []
        def clear_term():
            old_clear_term()
            clear_term_called.append(True)
        ui.ui_factory.clear_term = clear_term
        try:
            self.assertProduces(content)
        finally:
            ui.ui_factory.clear_term = old_clear_term
        self.assertEqual([True], clear_term_called)

    def test_aborts_on_unicode(self):
        """You can't sign Unicode text; it must be encoded first."""
        self.assertRaises(errors.BzrBadParameterUnicode,
                          self.assertProduces, u'foo')

    def import_keys(self):
        from StringIO import StringIO
        import gpgme
        context = gpgme.Context()

        key = StringIO("""-----BEGIN PGP PUBLIC KEY BLOCK-----
Version: GnuPG v1.4.11 (GNU/Linux)

mQENBE343IgBCADwzPW7kmKb2bjB+UU+1ER/ABMZspvtoZMPusUw7bk6coXHF/0W
u1K/hSYeX9xaGOfOQw41r/g13MoR9dsL6L84RLiisf38rRoBZt+d5bCbZA5Xo801
2PeoBoGo6u5oOYKAFLMvrUitPiiE0IT/oQTfC4YUrLN4A+9W0QZruPGIpIXwmZXr
L0zsqYfNqIN0ompeJenVpKpvm3loJ/zfK7R3EJ3hsv6nkUmWCFsP1Pw3UV1YuCmw
Mkdn1U7DaOql1WjXgj9ABQDJrun2TGsqrSRzBODtHKA/uOX0K3VfKBU8VZo3dXUm
1Q4ZeZC39L9qJGTH8TQYlwBLe1yAOp+vx7QJABEBAAG0JEJhemFhciBUZXN0IEtl
eSA8YmF6YWFyQGV4YW1wbGUuY29tPokBOAQTAQIAIgUCTfjciAIbAwYLCQgHAwIG
FQgCCQoLBBYCAwECHgECF4AACgkQh2gbHuMIDkWJUggAwj537fH6WW+GGLA5onys
2hZmXUq/tU+L92bjQoRY4fmsQpk/FUVPUf+NQ0v1gkxx4BTfyYewaj5G6L8cvqW2
jj7UiJd8z9gTRxWTnYwfR/w5PGmxfJsBfEUKWsccrPQdOXAhwu0fjYIVk4nqgswa
IOAZIwe5Vsfs36uSS7p8RQHAZXLXtTOn3KcXHaxu83w6nc4zkWRovGJ9isBN3haO
2qEa0mYiAfDpz40CGtb8N/TQHF3Xcw8rJcxpg6RF3jMtWQnzbVJFp13it00R3LqW
o/r3RII3Ii3z2yARlg6D+5hVOrFBV8jFLkff1R2ZnVu+7WOrnbpmt3OiMkSeZrtB
OrkBDQRN+NyIAQgArRZ2YGzUj5dXOVIWgZ1/QFpyfx/cG/293WjRE4Wt2e4SxMf2
V0dcVCqWwT0+a79Wbausv4bStD4SkwDmu0Jf3z5ERzrr7oZwP0PMsIlM5zT6XSsr
6UUneB3UXX7MrEqVogVhRM0ORIaK/oRwMXr7K6xVT+bCBP3/p66kHtY1ZpfEzTEX
imBsN3GqoewBHYIneJKBtHE7uzdzw3O5p5dXqoj5foxGi9R1J15vAmt5pI68HJeX
P6ktvXbX2Iu7VDNoCvRXM9+ntyJtsXCjNXg4pTGHS/XO4nm2db4FUZOBcVMb1vCc
VtFjLTcbCqJqpoJWUtsLcNqDqMHOQDpe6KTNTQARAQABiQEfBBgBAgAJBQJN+NyI
AhsMAAoJEIdoGx7jCA5FrR8IANnOF3PUj1TbRcwV6RoWmHsFQHrPmM8ogXia1Lsv
jE1iEWoC+muvKh6Oydf90k6ZslS7rdDnp2qzYY8W/TiDkxP+fvsZ4mMi1Y0F+3ty
1jzWhcsnB2VrJSiavxEXk0tKPrNv4EUGWG6wHsC9TBj37If+nrMyim94VHvI0eHm
X8yMlN4O3HfmgD9CbJdUxueP3e31OIYuwh/6F7GII8TNEVHU/8vh/mQcCxppNbc+
boff+kIsoa/TAMLwtJoSrX1nXm0K3vZePRLnIgmwVzdkOIkaRJUG2tSQFvkfhvtE
LhnkL5l4MO0wrUds0UWRwa3d7j/P2ExrqXdlLmEzrifWyEQ=
=hUJn
-----END PGP PUBLIC KEY BLOCK-----
""")

        secret_key = StringIO("""-----BEGIN PGP PRIVATE KEY BLOCK-----
Version: GnuPG v1.4.11 (GNU/Linux)

lQOYBE343IgBCADwzPW7kmKb2bjB+UU+1ER/ABMZspvtoZMPusUw7bk6coXHF/0W
u1K/hSYeX9xaGOfOQw41r/g13MoR9dsL6L84RLiisf38rRoBZt+d5bCbZA5Xo801
2PeoBoGo6u5oOYKAFLMvrUitPiiE0IT/oQTfC4YUrLN4A+9W0QZruPGIpIXwmZXr
L0zsqYfNqIN0ompeJenVpKpvm3loJ/zfK7R3EJ3hsv6nkUmWCFsP1Pw3UV1YuCmw
Mkdn1U7DaOql1WjXgj9ABQDJrun2TGsqrSRzBODtHKA/uOX0K3VfKBU8VZo3dXUm
1Q4ZeZC39L9qJGTH8TQYlwBLe1yAOp+vx7QJABEBAAEAB/0RJTbV991SOtVfPQVu
LM+tD0SiOXJwIBIINlngsFHWVIiBSDb6uF8dneMR70IRnuEFHFyAUXA7PZDxvcSu
phAqIdKCWxQPkAULAS0o4U2K3ZFGh4uOqvfZ8eSnh1rETFv7Yf3u23K89cZiy99n
EtWgSqzC/2z5PaZ7/alsYCBqhHuyd4Phaud7qv7FTz8mFrCf+CCY+D08wbnZBu4g
N9tBwoxT/UKRfv3nghIh9v+3qWfBEFGhrYbt92XKFbHOQeATZz8AGIv1eqN/+ZQY
oYmvVfO3GkrWaRoPeJNLqSDEn/45O1Uh9MJ4mQclXqB0QzMShle8uusHxIeJSQsR
z//VBAD11WS7qSgCeiHR+4jDzrrlb2snnA2bfDToEomDxd/n8xm7nJWdkNfJ2BCw
KvnxYVxjFNAwkKJGRajzALBLzRVO+K9NtSLiddv5zv+UNdgsKuE8tD7Jqxd/IbWw
AimCtL8osnJ+r9dvL+NyjkAT6l/NdEbLXGrBaMeTfSgl2cBOOwQA+sJIh1R5PiCK
nLIs9pm3PSy3w92Peelq/x/+0aebTZaJUk2ou3oCvB3druDqrUeaopuuCc0drV7C
Ldoey8x/T2ZGzmT2af9qNaD6ScTimDodXcJdwlpobhZTKpsE4EyywpLXtlWte1x0
1Mq3llQsIdRdf3GLS+L207hWgKDiDosD/0SyOBO/IBDteeEzeN2hNE3A8oeVbvRS
XrS/3uj6oKmlWUBORYP8ptUrXPoVPmNz2y4GO+OysFtfct3Yqb+Sb/52SXMOHTox
2oLW08tkzfkDArU5aauMEPmyutGyJ+hGo7fsuLXzXR8OPw4yZJdzG1tRlP2TTKmq
Fx8G/Ik6bN4zTYK0JEJhemFhciBUZXN0IEtleSA8YmF6YWFyQGV4YW1wbGUuY29t
PokBOAQTAQIAIgUCTfjciAIbAwYLCQgHAwIGFQgCCQoLBBYCAwECHgECF4AACgkQ
h2gbHuMIDkWJUggAwj537fH6WW+GGLA5onys2hZmXUq/tU+L92bjQoRY4fmsQpk/
FUVPUf+NQ0v1gkxx4BTfyYewaj5G6L8cvqW2jj7UiJd8z9gTRxWTnYwfR/w5PGmx
fJsBfEUKWsccrPQdOXAhwu0fjYIVk4nqgswaIOAZIwe5Vsfs36uSS7p8RQHAZXLX
tTOn3KcXHaxu83w6nc4zkWRovGJ9isBN3haO2qEa0mYiAfDpz40CGtb8N/TQHF3X
cw8rJcxpg6RF3jMtWQnzbVJFp13it00R3LqWo/r3RII3Ii3z2yARlg6D+5hVOrFB
V8jFLkff1R2ZnVu+7WOrnbpmt3OiMkSeZrtBOp0DlwRN+NyIAQgArRZ2YGzUj5dX
OVIWgZ1/QFpyfx/cG/293WjRE4Wt2e4SxMf2V0dcVCqWwT0+a79Wbausv4bStD4S
kwDmu0Jf3z5ERzrr7oZwP0PMsIlM5zT6XSsr6UUneB3UXX7MrEqVogVhRM0ORIaK
/oRwMXr7K6xVT+bCBP3/p66kHtY1ZpfEzTEXimBsN3GqoewBHYIneJKBtHE7uzdz
w3O5p5dXqoj5foxGi9R1J15vAmt5pI68HJeXP6ktvXbX2Iu7VDNoCvRXM9+ntyJt
sXCjNXg4pTGHS/XO4nm2db4FUZOBcVMb1vCcVtFjLTcbCqJqpoJWUtsLcNqDqMHO
QDpe6KTNTQARAQABAAf1EfceUlGLvoA/+yDTNTMjuPfzfKwbB/FOVfX44g3Za1eT
v7RvSuj4rFYIdE9UvZEei/pqPOSc+hhSsKZCulGXD5TUpf3AyG7ipWU/kID46Csp
0V08DPpFHnuw/N6+qNo5iSnhN9U1XMLjYT5d1HvKur26r2vWbmUTSJ1qIluHL2fT
R1pKYYLuoff4MIjZ01Hawq72jjor+dLBmMWveHpq4XNp+vQ4x8aFnY9ozufon0nM
uRSJRlQjDNB274tvUbmDFP+nzNbqF1nBTZ6FTdH/iKVNbytiYF7Hbat8GWVZqY1u
CZr7BklpIVWlk62ll0psMIPVyANi7YT332LLqYmBBADJKTx2dariG/kWU2W/9VEO
2VZpqsqazAxOoFEIOpcOlByhhyw5g0IKu0UyzHkhoCje0cWxpdSBFG432b8zL0AT
Z0RycfUG7Sgp9CpY1h8Cc/HbBa8xo1fSM7zplPQrHBqUzlVVBq6HOkUq+7qsPFWc
RRie95VsDmIMKQKPJHeYHQQA3EYGit+QHV0dccAInghEsf/mq8Gfnvo6HPYhWcDC
DTM39NhNlnl1WkTFCd2TWc+TWQ4KlRsh6bMjUpNa2qjrUl90fLekbogcxxMhcwa6
xgzEANZfwqdY0u3aB/CyZ6odfThwcAoeqoMpw34CfeKEroubpi2n8wKByrN2MQXJ
4vEEAJbXZOqgAcFAFBUVb5mVT0s2lJMagZFPdhRJz2bttz01s/B8aca6CrDpFRjT
03zRFUZjwDYqZDWBC181dCE9yla4OkWd5QyRKSS2EE02KEYqRzT0RngQn7s4AW2r
326up3Jhleln3hgD4Kk3V3KHmyK8zqZA0qWzry4Vl2jjkbnAPB2JAR8EGAECAAkF
Ak343IgCGwwACgkQh2gbHuMIDkWtHwgA2c4Xc9SPVNtFzBXpGhaYewVAes+YzyiB
eJrUuy+MTWIRagL6a68qHo7J1/3STpmyVLut0OenarNhjxb9OIOTE/5++xniYyLV
jQX7e3LWPNaFyycHZWslKJq/EReTS0o+s2/gRQZYbrAewL1MGPfsh/6eszKKb3hU
e8jR4eZfzIyU3g7cd+aAP0Jsl1TG54/d7fU4hi7CH/oXsYgjxM0RUdT/y+H+ZBwL
Gmk1tz5uh9/6Qiyhr9MAwvC0mhKtfWdebQre9l49EuciCbBXN2Q4iRpElQba1JAW
+R+G+0QuGeQvmXgw7TCtR2zRRZHBrd3uP8/YTGupd2UuYTOuJ9bIRA==
=LXn0
-----END PGP PRIVATE KEY BLOCK-----
""")

        context.import_(key)
        context.import_(secret_key)

    def test_verify_valid(self):
        try:
            self.import_keys()
        except ImportError:
            return True #can't test if gpgme isn't installed
            
        content = """-----BEGIN PGP SIGNED MESSAGE-----
Hash: SHA1

bazaar-ng testament short form 1
revision-id: amy@example.com-20110527185938-hluafawphszb8dl1
sha1: 6411f9bdf6571200357140c9ce7c0f50106ac9a4
-----BEGIN PGP SIGNATURE-----
Version: GnuPG v1.4.11 (GNU/Linux)

iQEcBAEBAgAGBQJN+ekFAAoJEIdoGx7jCA5FGtEH/i+XxJRvqU6wdBtLVrGBMAGk
FZ5VP+KyXYtymSbgSstj/vM12NeMIeFs3xGnNnYuX1MIcY6We5TKtCH0epY6ym5+
6g2Q2QpQ5/sT2d0mWzR0K4uVngmxVQaXTdk5PdZ40O7ULeDLW6CxzxMHyUL1rsIx
7UBUTBh1O/1n3ZfD99hUkm3hVcnsN90uTKH59zV9NWwArU0cug60+5eDKJhSJDbG
rIwlqbFAjDZ7L/48e+IaYIJwBZFzMBpJKdCxzALLtauMf+KK8hGiL2hrRbWm7ty6
NgxfkMYOB4rDPdSstT35N+5uBG3n/UzjxHssi0svMfVETYYX40y57dm2eZQXFp8=
=iwsn
-----END PGP SIGNATURE-----
"""
        my_gpg = gpg.GPGStrategy(FakeConfig())
        my_gpg.set_acceptable_keys("bazaar@example.com")
        self.assertEqual(gpg.SIGNATURE_VALID, my_gpg.verify(content))

    def test_verify_invalid(self):
        content = """-----BEGIN PGP SIGNED MESSAGE-----
Hash: SHA1

bazaar-ng testament short form 1
revision-id: amy@example.com-20110527185938-hluafawphszb8dl1
sha1: 6411f9bdf6571200357140c9ce7c0f50106ac9a4
-----BEGIN PGP SIGNATURE-----
Version: GnuPG v1.4.11 (GNU/Linux)

iEYEARECAAYFAk33gYsACgkQpQbm1N1NUIhiDACglOuQDlnSF4NxfHSkN/zrmFy8
nswAoNGXAVuR9ONasAKIGBNUE0b+lols
=SOuC
-----END PGP SIGNATURE-----
"""
        my_gpg = gpg.GPGStrategy(FakeConfig())
        self.assertEqual(gpg.SIGNATURE_NOT_VALID, my_gpg.verify(content))

    def test_set_acceptable_keys(self):
        try:
            self.import_keys()
        except ImportError:
            return True #can't test if gpgme isn't installed
        my_gpg = gpg.GPGStrategy(FakeConfig())
        my_gpg.set_acceptable_keys("bazaar@example.com")
        self.assertEqual(my_gpg.acceptable_keys,
                         [u'B5DEED5FCB15DAE6ECEF919587681B1EE3080E45'])

    def test_set_acceptable_keys_unknown(self):
        my_gpg = gpg.GPGStrategy(FakeConfig())
        my_gpg.set_acceptable_keys("unknown")
        self.assertEqual(my_gpg.acceptable_keys, [])
        

class TestDisabled(TestCase):

    def test_sign(self):
        self.assertRaises(errors.SigningFailed,
                          gpg.DisabledGPGStrategy(None).sign, 'content')

    def test_verify(self):
        self.assertRaises(errors.VerifyFailed,
                          gpg.DisabledGPGStrategy(None).verify, 'content')
