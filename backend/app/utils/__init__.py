"""Utility functions for the application"""
from app.utils.logging import setup_logging, get_logger
from app.utils.normalization import (
    normalize_company_name,
    normalize_address,
    normalize_phone,
    normalize_date,
    normalize_tax_id,
    normalize_text,
    names_are_equivalent,
    addresses_are_equivalent,
    similarity_ratio,
)

__all__ = [
    "setup_logging",
    "get_logger",
    "normalize_company_name",
    "normalize_address",
    "normalize_phone",
    "normalize_date",
    "normalize_tax_id",
    "normalize_text",
    "names_are_equivalent",
    "addresses_are_equivalent",
    "similarity_ratio",
]
