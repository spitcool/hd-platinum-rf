# SPDX-FileCopyrightText: 2026 Christopher Spitler
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Product identifiers and controls observed in Platinum Android 1.1 (build 14).

These are room product codes, not indices in the app's selection list. The
feature tuples describe the app's position controls; they do not authorize RF
operations or establish support by any backend, shade, or other app version.
"""

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping


@dataclass(frozen=True)
class Product:
    """An observed room product and its app-selected position feature codes."""

    code: int
    name: str
    position_features: tuple[int, ...]


PRODUCTS: Mapping[int, Product] = MappingProxyType({
    product.code: product for product in (
        Product(0, "Alustra® Woven Textures® Roller", (4,)),
        Product(1, "Duette® & Applause® Honeycomb Shades", (4,)),
        Product(2, "Duette® & Applause® Honeycomb Shades DuoLite™ & Top-Down/Bottom-Up", (4, 18)),
        Product(3, "Duette® & Applause® Honeycomb Shades Top-Down", (4,)),
        Product(4, "Duette® & Applause® Honeycomb Shades Skylift", (4,)),
        Product(5, "Designer Roller & Screen Shades", (4,)),
        Product(6, "Luminette® Privacy Sheers", (4, 7, 19)),
        Product(7, "Luminette® Modern Draperies Full Panel", (4,)),
        Product(8, "Luminette® Modern Draperies Dual Panel", (4, 7, 19)),
        Product(9, "Pirouette® Window Shadings", (4, 7)),
        Product(10, "Silhouette® & Nantucket™ Window Shadings", (4, 7)),
        Product(11, "Vignette® Modern Roman Shades Traditional", (4,)),
        Product(12, "Vignette® Modern Roman Shades Tiered™", (4,)),
        Product(13, "Vignette® Modern Roman Shades Tiered™ Top-Down/Bottom-Up", (4, 18)),
        Product(14, "Skyline® Gliding Window Panels", (4,)),
        Product(15, "Pleated Shades", (4,)),
        Product(16, "Alustra® Woven Textures® Roman", (4,)),
        Product(17, "Solera® Soft Shades", (4,)),
        Product(18, "Design Studio™ Roman Shades", (4,)),
        Product(21, "Silhouette® & Nantucket™ Window Shadings A Deux™ Room Darkening Shade", (4,)),
        Product(22, "Provenance® Woven Wood Shades", (4,)),
        Product(23, "Provenance® Woven Wood Shades Independent Operable Liner", (4,)),
        Product(24, "Provenance® Woven Wood Shades Vertical Drapery", (4,)),
        Product(25, "Provenance® Woven Wood Shades Top-Down/Bottom-Up", (4, 18)),
        Product(30, "Alustra® Woven Textures® Independently Operated Liner", (4,)),
    )
})


def validate_product_code(value: object) -> int:
    """Validate a code for new or edited room metadata without coercion.

    Unknown codes are rejected rather than mapped to a default product. This
    helper does not need to be applied when preserving an imported snapshot.
    """
    if type(value) is not int or value not in PRODUCTS:
        raise ValueError("product code must be an integer identifying a known Platinum product")
    return value


def get_product(code: int) -> Product:
    """Return the immutable catalog entry, raising ValueError for invalid codes."""
    return PRODUCTS[validate_product_code(code)]
