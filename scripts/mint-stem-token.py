#!/usr/bin/env python3
"""Mint a stem token from the signing key, for testing and for curl.

The point of the whole token design is that the success path can be exercised
without the site password -- which is what made the previous basic-auth Worker
untestable and got the live site broken twice. This is that exercise.

Usage:
  scripts/mint-stem-token.py                 # a week, like the real endpoint
  scripts/mint-stem-token.py --ttl -60       # already expired, for the reject test
  scripts/mint-stem-token.py --key FILE
"""
import argparse, base64, hashlib, hmac, os, time

DEFAULT_KEY = os.path.expanduser('~/.beatznbox/stem-token.key')


def mint(key, ttl):
    exp = int(time.time()) + ttl
    msg = f'v1.{exp}'
    sig = base64.urlsafe_b64encode(
        hmac.new(key.encode(), msg.encode(), hashlib.sha256).digest()
    ).decode().rstrip('=')
    return f'{msg}.{sig}'


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--key', default=DEFAULT_KEY)
    ap.add_argument('--ttl', type=int, default=7 * 24 * 3600)
    a = ap.parse_args()
    with open(a.key, encoding='utf-8') as f:
        print(mint(f.read().strip(), a.ttl))
