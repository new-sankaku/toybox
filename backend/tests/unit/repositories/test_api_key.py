import pytest
from repositories.api_key import ApiKeyRepository
from models.tables import ApiKeyStore


class TestApiKeyRepository:
    def test_save_new_key(self, db_session):
        repo = ApiKeyRepository(db_session)
        key_store = repo.save("anthropic", "sk-test-key-12345")
        assert key_store.provider_id == "anthropic"
        assert key_store.key_hint == "sk-...345"
        assert key_store.is_valid is False

    def test_save_update_existing(self, db_session):
        repo = ApiKeyRepository(db_session)
        repo.save("anthropic", "sk-old-key")
        repo.save("anthropic", "sk-new-key-67890")
        key_store = repo.get("anthropic")
        assert key_store.key_hint == "sk-...890"

    def test_get_nonexistent(self, db_session):
        repo = ApiKeyRepository(db_session)
        result = repo.get("nonexistent")
        assert result is None

    def test_get_all(self, db_session):
        repo = ApiKeyRepository(db_session)
        repo.save("anthropic", "sk-ant-key")
        repo.save("openai", "sk-openai-key")
        all_keys = repo.get_all()
        assert len(all_keys) == 2

    def test_get_all_hints(self, db_session):
        repo = ApiKeyRepository(db_session)
        repo.save("anthropic", "sk-ant-test-key")
        hints = repo.get_all_hints()
        assert "anthropic" in hints
        assert "hint" in hints["anthropic"]

    def test_delete(self, db_session):
        repo = ApiKeyRepository(db_session)
        repo.save("anthropic", "sk-test")
        deleted = repo.delete("anthropic")
        assert deleted is True
        assert repo.get("anthropic") is None

    def test_delete_nonexistent(self, db_session):
        repo = ApiKeyRepository(db_session)
        deleted = repo.delete("nonexistent")
        assert deleted is False

    def test_get_decrypted_key(self, db_session):
        repo = ApiKeyRepository(db_session)
        original = "sk-ant-secret-key-12345"
        repo.save("anthropic", original)
        decrypted = repo.get_decrypted_key("anthropic")
        assert decrypted == original

    def test_update_validation_status(self, db_session):
        repo = ApiKeyRepository(db_session)
        repo.save("anthropic", "sk-test")
        repo.update_validation_status("anthropic", True)
        key_store = repo.get("anthropic")
        assert key_store.is_valid is True
        assert key_store.last_validated_at is not None
