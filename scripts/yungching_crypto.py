import argparse
import base64
import hashlib
import json
from typing import Any

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


SERVICE_NAME = "YungChing.Buy"
SALT = bytes([2, 7, 0, 5, 1, 3, 8, 0])
ITERATIONS = 1000
DERIVED_LENGTH = 48

# Values independently derived from the current public Yongching frontend code.
EXPECTED_KEY_HEX = "936b60d69a2ae5668dcb279eabf5e76a64a2669d216da291c4ed71dbc4d3d9ae"
EXPECTED_IV_HEX = "3aab9af1a3d329ee4026b809990ae35b"


def derive_key_iv(service_name: str = SERVICE_NAME) -> tuple[bytes, bytes]:
    """Mirror the Yongching browser derivation: SHA-256 -> PBKDF2-SHA1 -> 32B key + 16B IV."""
    password = hashlib.sha256(service_name.encode("utf-8")).digest()
    derived = hashlib.pbkdf2_hmac(
        "sha1",
        password,
        SALT,
        ITERATIONS,
        dklen=DERIVED_LENGTH,
    )
    return derived[:32], derived[32:48]


def decrypt_text(ciphertext_b64: str, service_name: str = SERVICE_NAME) -> str:
    """Decrypt one Base64 AES-256-CBC response string and remove PKCS#7 padding."""
    key, iv = derive_key_iv(service_name)
    encrypted = base64.b64decode(ciphertext_b64)
    decryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    padded = decryptor.update(encrypted) + decryptor.finalize()
    unpadder = padding.PKCS7(128).unpadder()
    plain = unpadder.update(padded) + unpadder.finalize()
    return plain.decode("utf-8")


def decrypt_value(ciphertext_b64: str, service_name: str = SERVICE_NAME) -> Any:
    text = decrypt_text(ciphertext_b64, service_name)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def encrypt_value(value: Any, service_name: str = SERVICE_NAME) -> str:
    """Mirror the frontend request encryption for future API probing."""
    key, iv = derive_key_iv(service_name)
    if isinstance(value, str):
        raw = value.encode("utf-8")
    else:
        raw = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    padder = padding.PKCS7(128).padder()
    padded = padder.update(raw) + padder.finalize()
    encryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    encrypted = encryptor.update(padded) + encryptor.finalize()
    return base64.b64encode(encrypted).decode("ascii")


def self_test() -> dict[str, Any]:
    key, iv = derive_key_iv()
    sample = {"road": "中山路二段", "n": 1}
    roundtrip = decrypt_value(encrypt_value(sample))
    result = {
        "service": SERVICE_NAME,
        "algorithm": "AES-256-CBC",
        "kdf": "SHA-256(service) -> PBKDF2-HMAC-SHA1(iterations=1000, salt=0207000501030800, dkLen=48)",
        "keyHex": key.hex(),
        "ivHex": iv.hex(),
        "knownVectorMatch": key.hex() == EXPECTED_KEY_HEX and iv.hex() == EXPECTED_IV_HEX,
        "roundtripOk": roundtrip == sample,
    }
    if not result["knownVectorMatch"] or not result["roundtripOk"]:
        raise RuntimeError(f"Yongching crypto self-test failed: {result}")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--decrypt", help="Base64 AES-CBC ciphertext")
    args = parser.parse_args()

    if args.decrypt:
        print(json.dumps(decrypt_value(args.decrypt), ensure_ascii=False, indent=2))
        return

    print(json.dumps(self_test(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
