# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Allow running mycelium as a module: python -m mycelium"""

from mycelium.cli import app

if __name__ == "__main__":
    app()
