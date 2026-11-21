"""Check that EWNS publication keeps all course content encrypted."""

import base64
import json
from pathlib import Path
import tempfile
import unittest

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from prepare_ewns import PARAMETERS, SLIDES, prepare


class EncryptedCourseTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.source = Path(self.temporary.name) / "source"
        self.output = Path(self.temporary.name) / "output"
        published = self.source / "04_web_interactiva/publicar"
        published.mkdir(parents=True)
        theory = self.source / "01_teoria"
        theory.mkdir()
        self.password = "test-only-random-password"
        salt = b"0123456789abcdef"
        self.key = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=600000).derive(
            ("ceste:" + self.password).encode()
        )
        payload = json.dumps({"html": "<main>Private course content</main>", "js": ""}).encode()
        for index, name in enumerate(("index.html", "s1.html", "s2.html", "s3.html")):
            iv = index.to_bytes(12, "big")
            ciphertext = AESGCM(self.key).encrypt(iv, payload, None)
            encode = lambda value: base64.b64encode(value).decode()
            (published / name).write_text(
                '<meta name="robots" content="noindex,nofollow"><script>'
                f'const SALT="{encode(salt)}",IV="{encode(iv)}",CT="{encode(ciphertext)}",IT=600000;</script>'
            )
        (published / "style.css").write_text("body { color: black; }")
        for filename, _ in SLIDES:
            (theory / filename).write_bytes(b"%PDF-1.7\nprivate slide bytes\n")

    def test_all_pages_and_slides_remain_encrypted(self):
        prepare(self.source, "CESTE", self.password, self.output)
        self.assertEqual(len(list(self.output.iterdir())), 8)
        for path in self.output.glob("*.html"):
            text = path.read_text()
            self.assertNotIn("Private course content", text)
            self.assertNotIn("private slide bytes", text)
            self.assertNotIn(self.password, text)
            self.assertIn("noindex,nofollow", text)
            _, iv, ciphertext, iterations = PARAMETERS.search(text).groups()
            self.assertEqual(iterations, "600000")
            payload = json.loads(AESGCM(self.key).decrypt(base64.b64decode(iv), base64.b64decode(ciphertext), None))
            if path.name.startswith("teoria-"):
                number = int(path.stem.split("-")[1])
                filename, _ = SLIDES[number - 1]
                encoded_pdf = base64.b64encode((self.source / "01_teoria" / filename).read_bytes()).decode()
                self.assertIn(encoded_pdf, payload["js"])
                self.assertIn('download="' + filename + '"', payload["html"])
            else:
                self.assertIn("Private course content", payload["html"])
                if path.name == "index.html":
                    self.assertIn("teoria-3.html", payload["html"])
        self.assertFalse(list(self.output.glob("*.pdf")))

    def test_wrong_password_does_not_publish_anything(self):
        with self.assertRaises(InvalidTag):
            prepare(self.source, "ceste", "incorrect", self.output)
        self.assertFalse(self.output.exists())

    def test_plaintext_source_is_rejected(self):
        (self.source / "04_web_interactiva/publicar/s2.html").write_text("Private plaintext page")
        with self.assertRaisesRegex(ValueError, "refusing to copy unencrypted"):
            prepare(self.source, "ceste", self.password, self.output)
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
