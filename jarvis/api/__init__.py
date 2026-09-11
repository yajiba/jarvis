"""Local dashboard API."""

__all__ = ["create_app"]


def __getattr__(name: str):
    # Keep module startup from importing server before runpy executes it.
    if name == "create_app":
        from .server import create_app

        return create_app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
