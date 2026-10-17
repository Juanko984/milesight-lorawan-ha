"""LoRaWAN 1.0.x cryptography: AES-128 and AES-CMAC (the `cryptography` package ships with Home Assistant)."""
from __future__ import annotations

from cryptography.hazmat.primitives import cmac
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


def aes_encrypt(key: bytes, block: bytes) -> bytes:
    enc = Cipher(algorithms.AES(key), modes.ECB()).encryptor()
    return enc.update(block) + enc.finalize()


def aes_decrypt(key: bytes, block: bytes) -> bytes:
    dec = Cipher(algorithms.AES(key), modes.ECB()).decryptor()
    return dec.update(block) + dec.finalize()


def aes_cmac(key: bytes, msg: bytes) -> bytes:
    c = cmac.CMAC(algorithms.AES(key))
    c.update(msg)
    return c.finalize()


# ------------------------------------------------------------------ join
def join_request_mic(app_key: bytes, msg: bytes) -> bytes:
    """msg = MHDR | JoinEUI | DevEUI | DevNonce."""
    return aes_cmac(app_key, msg)[:4]


def join_accept_encrypt(app_key: bytes, mhdr: bytes, body: bytes) -> bytes:
    """body = JoinNonce | NetID | DevAddr | DLSettings | RxDelay | [CFList] (little-endian fields as sent).
    Returns the complete PHYPayload: MHDR | aes_decrypt(AppKey, body | MIC)."""
    mic = aes_cmac(app_key, mhdr + body)[:4]
    clear = body + mic
    return mhdr + b"".join(aes_decrypt(app_key, clear[i:i + 16]) for i in range(0, len(clear), 16))


def join_accept_decrypt(app_key: bytes, phy: bytes) -> bytes:
    """Device side (tests): the clear body | MIC of a join-accept."""
    enc = phy[1:]
    return b"".join(aes_encrypt(app_key, enc[i:i + 16]) for i in range(0, len(enc), 16))


def session_keys(app_key: bytes, join_nonce: bytes, net_id: bytes, dev_nonce: bytes) -> tuple[bytes, bytes]:
    """LoRaWAN 1.0.x: (NwkSKey, AppSKey). join_nonce / net_id / dev_nonce little-endian as on air."""
    pad = bytes(7)
    nwk = aes_encrypt(app_key, b"\x01" + join_nonce + net_id + dev_nonce + pad)
    app = aes_encrypt(app_key, b"\x02" + join_nonce + net_id + dev_nonce + pad)
    return nwk, app


# ------------------------------------------------------------------ data frames
def data_mic(nwk_s_key: bytes, msg: bytes, dev_addr: int, fcnt: int, uplink: bool) -> bytes:
    """msg = MHDR | FHDR | FPort | FRMPayload (everything before the MIC)."""
    b0 = (b"\x49" + bytes(4) + bytes([0 if uplink else 1]) + dev_addr.to_bytes(4, "little")
          + (fcnt & 0xFFFFFFFF).to_bytes(4, "little") + b"\x00" + bytes([len(msg)]))
    return aes_cmac(nwk_s_key, b0 + msg)[:4]


def crypt_payload(key: bytes, payload: bytes, dev_addr: int, fcnt: int, uplink: bool) -> bytes:
    """Encrypts or decrypts FRMPayload (the same operation both ways)."""
    out = bytearray()
    for i in range(0, len(payload), 16):
        a = (b"\x01" + bytes(4) + bytes([0 if uplink else 1]) + dev_addr.to_bytes(4, "little")
             + (fcnt & 0xFFFFFFFF).to_bytes(4, "little") + b"\x00" + bytes([i // 16 + 1]))
        s = aes_encrypt(key, a)
        out += bytes(x ^ y for x, y in zip(payload[i:i + 16], s))
    return bytes(out)
