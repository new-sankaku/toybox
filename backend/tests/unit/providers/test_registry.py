import pytest
from providers.registry import ProviderRegistry, register_all_providers, get_provider, list_providers
from providers.mock import MockProvider


class TestProviderRegistry:
    def test_register_provider(self):
        ProviderRegistry._providers.clear()
        ProviderRegistry._instances.clear()
        ProviderRegistry.register(MockProvider)
        assert ProviderRegistry.is_registered("mock")

    def test_get_provider(self):
        ProviderRegistry._providers.clear()
        ProviderRegistry._instances.clear()
        ProviderRegistry.register(MockProvider)
        provider = ProviderRegistry.get("mock")
        assert provider is not None
        assert provider.provider_id == "mock"

    def test_get_nonexistent_provider(self):
        ProviderRegistry._providers.clear()
        ProviderRegistry._instances.clear()
        provider = ProviderRegistry.get("nonexistent")
        assert provider is None

    def test_list_providers(self):
        ProviderRegistry._providers.clear()
        ProviderRegistry._instances.clear()
        ProviderRegistry.register(MockProvider)
        providers = ProviderRegistry.list_providers()
        assert len(providers) == 1
        assert providers[0]["id"] == "mock"

    def test_clear_cache(self):
        ProviderRegistry._providers.clear()
        ProviderRegistry._instances.clear()
        ProviderRegistry.register(MockProvider)
        ProviderRegistry.get("mock")
        assert len(ProviderRegistry._instances) > 0
        ProviderRegistry.clear_cache()
        assert len(ProviderRegistry._instances) == 0

    def test_get_fresh(self):
        ProviderRegistry._providers.clear()
        ProviderRegistry._instances.clear()
        ProviderRegistry.register(MockProvider)
        provider1 = ProviderRegistry.get("mock")
        provider2 = ProviderRegistry.get_fresh("mock")
        assert provider1 is not provider2


class TestRegisterAllProviders:
    def test_all_providers_registered(self):
        ProviderRegistry._providers.clear()
        ProviderRegistry._instances.clear()
        register_all_providers()
        expected = ["anthropic", "openai", "google", "xai", "mock", "zhipu", "deepseek"]
        for provider_id in expected:
            assert ProviderRegistry.is_registered(provider_id), f"{provider_id} not registered"


class TestShortcuts:
    def test_get_provider_shortcut(self):
        ProviderRegistry._providers.clear()
        ProviderRegistry._instances.clear()
        ProviderRegistry.register(MockProvider)
        provider = get_provider("mock")
        assert provider is not None

    def test_list_providers_shortcut(self):
        ProviderRegistry._providers.clear()
        ProviderRegistry._instances.clear()
        ProviderRegistry.register(MockProvider)
        providers = list_providers()
        assert len(providers) == 1
