#!/usr/bin/env python3
"""Encrypt the dashboard data for the GitHub Pages site.

Usage:
  python3 encrypt_data.py expenses.json analysis.json savings.json PASSWORD data.enc.json [debts.json]

savings.json is {"plan": [...], "entries": [...]}.
debts.json (optional) is Jorgie's debt payoff data: {"settings", "accounts", "payments", "plan_requests", "plan"}.
If debts.json is NOT given, the debts already stored in data.enc.json are kept as they are
(so a run that forgets the argument can never erase them).

The page (index.html) asks for the same password and decrypts in the browser
(PBKDF2-SHA256, 250,000 iterations -> AES-256-GCM). Nothing readable is stored in the repo.
"""
import base64, json, os, sys
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

ITER = 250_000


def derive(password, salt, iters):
    return PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=iters).derive(password.encode('utf-8'))


def read_existing(out, password):
    try:
        e = json.load(open(out))
        b = lambda k: base64.b64decode(e[k])
        return json.loads(AESGCM(derive(password, b('salt'), e['iter'])).decrypt(b('iv'), b('data'), None))
    except Exception:
        return {}


def main():
    if len(sys.argv) not in (6, 7):
        sys.exit('Usage: encrypt_data.py expenses.json analysis.json savings.json PASSWORD out.json [debts.json]')
    fe, fa, fs, password, out = sys.argv[1:6]
    savings = json.load(open(fs, encoding='utf-8'))
    if not isinstance(savings, dict) or 'entries' not in savings or 'plan' not in savings:
        sys.exit('savings.json must be {"plan": [...], "entries": [...]}')
    if len(sys.argv) == 7:
        debts = json.load(open(sys.argv[6], encoding='utf-8'))
        if not isinstance(debts, dict) or 'accounts' not in debts:
            sys.exit('debts.json must be {"settings": {...}, "accounts": [...], "payments": [...], ...}')
    else:
        debts = read_existing(out, password).get('debts')
    payload = {
        'expenses': json.load(open(fe, encoding='utf-8')),
        'analysis': json.load(open(fa, encoding='utf-8')),
        'savings': savings,
    }
    if debts is not None:
        payload['debts'] = debts
    salt = os.urandom(16); iv = os.urandom(12)
    ct = AESGCM(derive(password, salt, ITER)).encrypt(iv, json.dumps(payload, ensure_ascii=False).encode('utf-8'), None)
    b64 = lambda b: base64.b64encode(b).decode()
    json.dump({'v': 1, 'iter': ITER, 'salt': b64(salt), 'iv': b64(iv), 'data': b64(ct)}, open(out, 'w'))
    print('wrote', out, '(with debts)' if debts is not None else '')


if __name__ == '__main__':
    main()
