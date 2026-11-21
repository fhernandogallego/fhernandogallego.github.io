"""Prepare encrypted EWNS pages and slides without publishing source material.

Usage: python3 scripts/prepare_ewns.py /path/to/05_EWNS --user ceste
The password is requested privately and is never written to the repository.
"""

import argparse
import base64
import getpass
import html
import json
import os
from pathlib import Path
import re
import shutil

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


ROOT = Path(__file__).resolve().parents[1]
SLIDES = (
    ("01_senal.pdf", "La señal GNSS y por qué es frágil"),
    ("02_ataques.pdf", "Perturbar y engañar"),
    ("03_defensa.pdf", "Detectar y defender"),
)
PARAMETERS = re.compile(r'const SALT="([^"]+)",IV="([^"]+)",CT="([^"]+)",IT=(\d+);')


def prepare(source: Path, username: str, password: str, destination: Path) -> None:
    published = source / "04_web_interactiva" / "publicar"
    wrappers = {name: (published / name).read_text() for name in ("index.html", "s1.html", "s2.html", "s3.html")}
    parameters = {name: PARAMETERS.search(page) for name, page in wrappers.items()}
    if not all(parameters.values()):
        raise ValueError("Expected encrypted wrappers in publicar/; refusing to copy unencrypted pages")
    salt, _, _, iterations = parameters["index.html"].groups()
    key = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=base64.b64decode(salt), iterations=int(iterations)).derive(
        (username.strip().lower() + ":" + password).encode()
    )
    cipher = AESGCM(key)
    payloads = {}
    for name, match in parameters.items():
        page_salt, iv, ciphertext, page_iterations = match.groups()
        if (page_salt, page_iterations) != (salt, iterations):
            raise ValueError("The pages must share the same salt and iteration count for session access")
        payloads[name] = json.loads(cipher.decrypt(base64.b64decode(iv), base64.b64decode(ciphertext), None))

    def wrap(payload: dict, template: str) -> str:
        iv = os.urandom(12)
        ciphertext = cipher.encrypt(iv, json.dumps(payload, ensure_ascii=False).encode(), None)
        assignment = f'const SALT="{salt}",IV="{base64.b64encode(iv).decode()}",CT="{base64.b64encode(ciphertext).decode()}",IT={iterations};'
        return PARAMETERS.sub(lambda _: assignment, template, count=1)

    links = "".join(
        f'<a href="teoria-{number}.html"><h3>{number} · {html.escape(title)}</h3><p>Transparencias · PDF</p></a>'
        for number, (_, title) in enumerate(SLIDES, 1)
    )
    payloads["index.html"]["html"] = payloads["index.html"]["html"].replace(
        "</main>", f'<h2>Transparencias de teoría</h2><div class="cards">{links}</div><p><a href="/docencia/">← Docencia</a></p></main>'
    )
    output = {name: wrap(payloads[name], template) for name, template in wrappers.items()}
    for number, (filename, title) in enumerate(SLIDES, 1):
        pdf = (source / "01_teoria" / filename).read_bytes()
        if not pdf.startswith(b"%PDF-"):
            raise ValueError(f"Not a PDF: {filename}")
        payload = {
            "html": f'''<header class="top"><div class="in"><a href="index.html">CESTE · EWNS</a><h1>{html.escape(title)}</h1><p>Transparencias de teoría</p></div></header>
<main><nav class="tabs"><a href="index.html">Inicio</a><a href="s{number}.html">Ejercicios de la sesión {number}</a><a href="/docencia/">Docencia</a></nav>
<p><a id="pdf-download" class="pri" download="{filename}">Descargar PDF</a></p><p class="note">Si tu navegador no muestra el documento, utiliza el enlace de descarga.</p>
<iframe id="pdf-viewer" title="{html.escape(title)}" style="width:100%;height:78vh;border:1px solid var(--line);border-radius:8px"></iframe></main>
<footer>Francisco Hernando-Gallego · CESTE · EWNS · 2026/27</footer>''',
            "js": f'''document.title={json.dumps(title + ' · EWNS')};
const bytes=Uint8Array.from(atob({json.dumps(base64.b64encode(pdf).decode())}),c=>c.charCodeAt(0));
const pdfUrl=URL.createObjectURL(new Blob([bytes],{{type:'application/pdf'}}));
document.getElementById('pdf-download').href=pdfUrl;
document.getElementById('pdf-viewer').src=pdfUrl;
window.addEventListener('pagehide',()=>URL.revokeObjectURL(pdfUrl),{{once:true}});''',
        }
        output[f"teoria-{number}.html"] = wrap(payload, wrappers["index.html"].replace("Ejercicios EWNS", "Material EWNS"))

    destination.mkdir(parents=True, exist_ok=True)
    for name, text in output.items():
        text = text.replace('id="u" placeholder=', 'id="u" aria-label="Usuario" placeholder=')
        text = text.replace('id="p" type=', 'id="p" aria-label="Contraseña" type=')
        (destination / name).write_text(text)
    shutil.copyfile(published / "style.css", destination / "style.css")
    print(f"Prepared {len(output)} encrypted pages and style.css; no source pages or raw PDFs copied")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--user", default="ceste")
    args = parser.parse_args()
    prepare(args.source, args.user, getpass.getpass("EWNS password: "), ROOT / "ewns")
