#!/usr/bin/env python3
"""Encrypt the dashboard data for the GitHub Pages site.

Usage: python3 encrypt_data.py expenses.json analysis.json PASSWORD data.enc.json

The page (index.html) asks for the same password and decrypts in the browser
(PBKDF2-SHA256, 250,000 iterations -> AES-256-GCM). Nothing readable is stored in the repo.
"""
import base64, json, os, sys
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

ITER = 250_000

def main():
    fe, fa, password, out = sys.argv[1:5]
    payload = {
        'expenses': json.load(open(fe, encoding='utf-8')),
        'analysis': json.load(open(fa, encoding='utf-8')),
    }
    salt = os.urandom(16); iv = os.urandom(12)
    key = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=ITER).derive(password.encode('utf-8'))
    ct = AESGCM(key).encrypt(iv, json.dumps(payload, ensure_ascii=False).encode('utf-8'), None)
    b64 = lambda b: base64.b64encode(b).decode()
    json.dump({'v': 1, 'iter': ITER, 'salt': b64(salt), 'iv': b64(iv), 'data': b64(ct)}, open(out, 'w'))
    print('wrote', out)

if __name__ == '__main__':
    main()
