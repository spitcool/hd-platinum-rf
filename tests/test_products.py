# SPDX-FileCopyrightText: 2026 Christopher Spitler
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Product metadata validation without private APK files or radio access."""

from dataclasses import FrozenInstanceError
import unittest

from hd_platinum.products import PRODUCTS, get_product, validate_product_code


class ProductTests(unittest.TestCase):
    def test_all_observed_product_codes_are_room_codes_not_selection_indices(self):
        expected = set(range(19)) | {21, 22, 23, 24, 25, 30}
        self.assertEqual(set(PRODUCTS), expected)
        for code in expected:
            with self.subTest(code=code):
                self.assertEqual(validate_product_code(code), code)
                self.assertEqual(get_product(code).code, code)
                self.assertTrue(get_product(code).name)
        # The independent liner is the third selection, but its wire code is 30.
        self.assertEqual(get_product(30).name,
                         "Alustra® Woven Textures® Independently Operated Liner")
        self.assertEqual(get_product(2).name,
                         "Duette® & Applause® Honeycomb Shades DuoLite™ & Top-Down/Bottom-Up")

    def test_unknown_codes_are_not_silently_mapped_to_a_default(self):
        for code in (-1, 19, 20, 26, 27, 28, 29, 31, 99, 100, 2 ** 64):
            for operation in (get_product, validate_product_code):
                with self.subTest(code=code, operation=operation.__name__):
                    with self.assertRaisesRegex(ValueError, "known Platinum product"):
                        operation(code)

    def test_numeric_lookalikes_and_unhashable_inputs_are_rejected_without_coercion(self):
        for value in (True, False, 1.0, "1", "01", b"1", None, [], {}, {1}):
            for operation in (get_product, validate_product_code):
                with self.subTest(value=value, operation=operation.__name__):
                    with self.assertRaises(ValueError):
                        operation(value)

    def test_ui_feature_matrix_keeps_secondary_and_two_sided_tilt_distinct(self):
        self.assertTrue(all(4 in product.position_features for product in PRODUCTS.values()))
        expected = {18: {2, 13, 25}, 7: {6, 8, 9, 10}, 19: {6, 8}}
        for feature, product_codes in expected.items():
            with self.subTest(feature=feature):
                self.assertEqual({code for code, product in PRODUCTS.items()
                                  if feature in product.position_features}, product_codes)
        self.assertEqual({feature for product in PRODUCTS.values()
                          for feature in product.position_features}, {4, 7, 18, 19})

    def test_product_names_do_not_imply_unobserved_secondary_controls(self):
        for code in (21, 23, 30):
            with self.subTest(code=code):
                self.assertEqual(get_product(code).position_features, (4,))

    def test_shared_catalog_and_entries_cannot_be_mutated(self):
        with self.assertRaises(TypeError):
            PRODUCTS[0] = PRODUCTS[1]
        with self.assertRaises(FrozenInstanceError):
            get_product(0).name = "changed"
        with self.assertRaises(TypeError):
            get_product(6).position_features[0] = 12


if __name__ == "__main__":
    unittest.main()
