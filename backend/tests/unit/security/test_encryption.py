import pytest
from security.encryption import (
 encrypt_api_key,
 decrypt_api_key,
 generate_key_hint,
)


class TestEncryption:
 def test_encrypt_decrypt_roundtrip(self):
  original = "sk-ant-api03-test-key-12345"
  encrypted = encrypt_api_key(original)
  assert encrypted != original
  decrypted = decrypt_api_key(encrypted)
  assert decrypted == original

 def test_different_keys_different_ciphertext(self):
  key1 = "sk-key-1"
  key2 = "sk-key-2"
  enc1 = encrypt_api_key(key1)
  enc2 = encrypt_api_key(key2)
  assert enc1 != enc2

 def test_empty_string(self):
  encrypted = encrypt_api_key("")
  decrypted = decrypt_api_key(encrypted)
  assert decrypted == ""

 def test_unicode_key(self):
  original = "sk-日本語キー-12345"
  encrypted = encrypt_api_key(original)
  decrypted = decrypt_api_key(encrypted)
  assert decrypted == original

 def test_long_key(self):
  original = "sk-" + "a" * 1000
  encrypted = encrypt_api_key(original)
  decrypted = decrypt_api_key(encrypted)
  assert decrypted == original


class TestKeyHint:
 def test_normal_key(self):
  hint = generate_key_hint("sk-ant-api03-abcdefghijk")
  assert hint == "sk-...ijk"

 def test_short_key(self):
  hint = generate_key_hint("short")
  assert hint == "***"

 def test_exact_boundary(self):
  hint = generate_key_hint("12345678")
  assert hint == "***"

 def test_just_over_boundary(self):
  hint = generate_key_hint("123456789")
  assert hint == "123...789"
