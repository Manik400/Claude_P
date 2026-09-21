"""Reader for the encrypted files the phone site used to publish.

Nothing is encrypted any more: reports, the queue and the phone's requests
are committed to gh-pages as plain .html / .json and the phone page opens
them without a passphrase. This module only remains so the PC worker and
publish.py can read (and convert) files from before the change.

Old format (JSON, UTF-8):
    {"v": 1, "kdf": "pbkdf2-sha256", "iter": N, "salt": b64, "iv": b64, "ct": b64}
Key: PBKDF2-HMAC-SHA256(passphrase, salt, iter) -> 32 bytes. Cipher: AES-256-GCM.
"""
import base64
import json
import os


def config_path():
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "JobHuntPhone", "config.json")


def is_encrypted(blob):
    """True when `blob` is an old-format encrypted envelope."""
    if not blob.lstrip().startswith(b"{"):
        return False
    try:
        obj = json.loads(blob.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return False
    return isinstance(obj, dict) and obj.get("v") == 1 and "kdf" in obj and "ct" in obj


def decrypt_bytes(blob, passphrase):
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    obj = json.loads(blob.decode("utf-8"))
    key = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=base64.b64decode(obj["salt"]),
                     iterations=int(obj["iter"])).derive(passphrase.encode("utf-8"))
    return AESGCM(key).decrypt(base64.b64decode(obj["iv"]), base64.b64decode(obj["ct"]), None)


def read_plain(blob, passphrase=""):
    """The file's contents: as-is for plain files, decrypted for old ones (needs the passphrase)."""
    if not is_encrypted(blob):
        return blob
    if not passphrase:
        raise ValueError("encrypted with the old passphrase and no passphrase is available")
    return decrypt_bytes(blob, passphrase)


def get_passphrase():
    """The old passphrase, if still around (SITE_PASSPHRASE env or the PC config). May be ""."""
    p = os.environ.get("SITE_PASSPHRASE", "")
    if not p and os.path.exists(config_path()):
        try:
            with open(config_path(), encoding="utf-8") as f:
                p = json.load(f).get("passphrase", "")
        except (OSError, ValueError):
            p = ""
    return p
