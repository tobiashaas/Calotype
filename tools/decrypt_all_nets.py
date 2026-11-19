"""Batch decryptor for all Neurapix nets in F:\\nets.

Derives the key chains and decrypts all tokens for every available net model
into F:\\decrypted_nets\\<net_name>\\.
"""

import hashlib
import hmac
import io
import os
import sys
from pathlib import Path
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

USER_ID = "96d27d15-f1d4-4693-9dc5-51f837f06b48"

# Known net metadata: net_id -> alias
NETS_INFO = {
    "971878f0-9574-4e5e-8325-d3bfbc85d789v6": "wedding_v6",
    "971878f0-9574-4e5e-8325-d3bfbc85d789v4": "wedding_v4",
    "987b3adc-974a-4429-a69c-9097b42d885dv2": "kita_v2",
    "9d80a13d-3951-4dde-ad50-71a7661f8f55v2": "wedding_herbst_vs_v2",
    "9be49cd6-56af-430a-851e-a3c34d12d9d5v2": "vintage_sunbeam",
    "9be7fd6a-c954-4fda-9c76-23ceb1b00cb8v2": "luminous_dream",
    "9bfaaf71-fe80-4168-a455-88ee734089a1v2": "eternal_essence",
    "9bfc6f60-0911-46b5-81c7-b2bd6a37e759v2": "classic_depths_bw",
    "9c0a216d-3b79-44e6-abcd-3a44d6e76128v2": "gentle_mist_bw",
}

NETS_ROOT = Path(r"F:\nets")
OUT_ROOT = Path(r"F:\decrypted_nets")


def derive_chain(user_id: str, net_id: str, n: int = 16):
    prk = hmac.new(b'&' * 32, (user_id + net_id).encode(), hashlib.sha256).digest()
    keys, t = [], b''
    for i in range(1, n + 1):
        t = hmac.new(prk, (t if i > 1 else b'') + bytes([i]), hashlib.sha256).digest()
        keys.append(t)
    return keys


def find_tokens(path):
    size = os.path.getsize(path)
    offsets = [0]
    with open(path, 'rb') as f:
        off, carry = 0, b''
        while True:
            chunk = f.read(1 << 24)
            if not chunk:
                break
            buf = carry + chunk
            base = off - len(carry)
            i = 0
            while True:
                j = buf.find(b'\x80\x00\x00\x00', i)
                if j < 0:
                    break
                if buf[j + 4:j + 5] == b'\x00':
                    offsets.append(base + j)
                i = j + 1
            carry = buf[-8:]
            off += len(chunk)
    offsets = sorted(set(offsets))
    spans = []
    for a, b in zip(offsets, offsets[1:] + [size]):
        if (b - a) % 16 == 9:
            spans.append((a, b))
    if not spans or spans[0][0] != 0:
        spans = [(0, size)]
    return spans


def decrypt_token(f, start, end, aes_key):
    f.seek(start)
    head = f.read(25)
    if head[0] != 0x80:
        return None, None
    iv = head[9:25]
    dec = Cipher(algorithms.AES(aes_key), modes.CBC(iv)).decryptor()
    ct_len = end - start - 25 - 32
    out = io.BytesIO()
    remaining = ct_len
    while remaining > 0:
        chunk = f.read(min(1 << 24, remaining))
        out.write(dec.update(chunk))
        remaining -= len(chunk)
    data = out.getvalue()
    hmac_stored = f.read(32)
    return data, hmac_stored


def decrypt_net(net_id: str, alias: str, user_id: str):
    container_path = NETS_ROOT / net_id / net_id
    if not container_path.exists():
        print(f"[{alias}] Container not found at {container_path}, skipping.", flush=True)
        return

    out_dir = OUT_ROOT / alias
    out_dir.mkdir(parents=True, exist_ok=True)

    # Check if already decrypted
    tokens_exist = list(out_dir.glob("token*.bin"))
    if len(tokens_exist) >= 15:
        print(f"[{alias}] Already decrypted ({len(tokens_exist)} tokens present in {out_dir}).", flush=True)
        return

    print(f"\nDecrypting [{alias}] ({net_id}) from {container_path}...", flush=True)
    keys = derive_chain(user_id, net_id, 16)
    spans = find_tokens(container_path)
    print(f"  Found {len(spans)} token boundaries.", flush=True)

    decrypted_count = 0
    with open(container_path, 'rb') as f:
        for idx, (a, b) in enumerate(spans):
            matched = False
            for ki, key in enumerate(keys):
                d, hm = decrypt_token(f, a, b, key[16:])
                f.seek(0)
                if d and (d[:4] == b'PK\x03\x04' or d[:2] == b'\x80\x02' or d[:1] == b'\x80' or d[:2] == b'\x1f\x8b'):
                    fn = out_dir / f"token{idx:02d}.bin"
                    fn.write_bytes(d)
                    decrypted_count += 1
                    matched = True
                    break
            if not matched:
                print(f"  [Warning] Token {idx} could not be decrypted with derived keys.", flush=True)

    print(f"  Successfully decrypted {decrypted_count}/{len(spans)} tokens into {out_dir}", flush=True)


def main():
    print("=" * 60, flush=True)
    print("Starting Batch Decryption for all Neurapix Net Containers", flush=True)
    print("=" * 60, flush=True)

    for net_id, alias in NETS_INFO.items():
        try:
            decrypt_net(net_id, alias, USER_ID)
        except Exception as e:
            print(f"Error decrypting {alias}: {e}", flush=True)

    print("\nBatch Decryption Complete!", flush=True)


if __name__ == "__main__":
    main()
