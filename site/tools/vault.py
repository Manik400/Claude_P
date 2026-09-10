"""Encrypt / decrypt report files for the phone site.

The site is served from a public GitHub Pages branch, so every report is
encrypted before it is committed. The phone page asks for the passphrase once
and decrypts in the browser (WebCrypto), so nothing readable is ever public.

Format (JSON, UTF-8):
    {"v": 1, "kdf": "pbkdf2-sha256", "iter": N, "salt": b64, "iv": b64, "ct": b64}
Key: PBKDF2-HMAC-SHA256(passphrase, salt, iter) -> 32 bytes. Cipher: AES-256-GCM.

Usage:
    python vault.py encrypt <in> <out>      (passphrase from SITE_PASSPHRASE env or the PC config)
    python vault.py decrypt <in> <out>
"""
import base64
import json
import os
import sys

ITERATIONS = 200_000


def config_path():
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "JobHuntPhone", "config.json")


def _b64(b):
    return base64.b64encode(b).decode("ascii")


def _unb64(s):
    return base64.b64decode(s)


def encrypt_bytes(data, passphrase):
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    salt = os.urandom(16)
    iv = os.urandom(12)
    key = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=ITERATIONS).derive(
        passphrase.encode("utf-8"))
    ct = AESGCM(key).encrypt(iv, data, None)
    return json.dumps({"v": 1, "kdf": "pbkdf2-sha256", "iter": ITERATIONS,
                       "salt": _b64(salt), "iv": _b64(iv), "ct": _b64(ct)}).encode("utf-8")


def decrypt_bytes(blob, passphrase):
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    obj = json.loads(blob.decode("utf-8"))
    key = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=_unb64(obj["salt"]),
                     iterations=int(obj["iter"])).derive(passphrase.encode("utf-8"))
    return AESGCM(key).decrypt(_unb64(obj["iv"]), _unb64(obj["ct"]), None)


def get_passphrase():
    p = os.environ.get("SITE_PASSPHRASE", "")
    if not p and os.path.exists(config_path()):
        with open(config_path(), encoding="utf-8") as f:
            p = json.load(f).get("passphrase", "")
    return p


def main(argv):
    if len(argv) != 3 or argv[0] not in ("encrypt", "decrypt"):
        print(__doc__)
        return 2
    passphrase = get_passphrase()
    if not passphrase:
        print("vault: no passphrase (set SITE_PASSPHRASE or run setup_phone.bat)", file=sys.stderr)
        return 1
    with open(argv[1], "rb") as f:
        data = f.read()
    out = encrypt_bytes(data, passphrase) if argv[0] == "encrypt" else decrypt_bytes(data, passphrase)
    with open(argv[2], "wb") as f:
        f.write(out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
