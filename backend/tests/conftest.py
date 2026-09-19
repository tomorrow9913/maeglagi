"""Keep the shared test client from consuming the production request budget."""

import os

# API contract tests share one in-process app and client IP. The dedicated
# middleware test creates its own app with an explicit 1/minute limit.
os.environ.setdefault("RATE_LIMIT", "100000/minute")
