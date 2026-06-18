"""Allow ``python -m web_adapter``."""

from web_adapter.server import main

if __name__ == "__main__":
    raise SystemExit(main())
