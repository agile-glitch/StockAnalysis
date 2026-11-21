from .base import CachedProvider, Provider, ProviderError


def make_provider(demo: bool = False) -> CachedProvider:
    if demo:
        from .demo import DemoProvider
        return CachedProvider(DemoProvider())
    from .yahoo import YahooProvider
    return CachedProvider(YahooProvider())


__all__ = ["CachedProvider", "Provider", "ProviderError", "make_provider"]
