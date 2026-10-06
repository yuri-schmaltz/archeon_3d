"""Archeon 3D HTTP API layer.

Subpackage holding the FastAPI server, request contracts, the priority
job manager, SQLite persistence, auth and observability helpers.

This module deliberately exposes no eager imports: ``hy3dgen.api.config``
is read at import time by several other modules and pulls in Pydantic
settings, so importing this package stays cheap.
"""
