"""Shared helper functions used across every pipeline stage.

Each module is a focused, deterministic utility used across stages: string
normalization, numeric coercion, canonical sorting, dataframe cleaning, checkpoints,
elapsed-time formatting, filename token parsing, and guard assertions.
"""

from __future__ import annotations
