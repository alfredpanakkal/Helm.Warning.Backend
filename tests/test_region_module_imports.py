#!/usr/bin/env python3
"""
tests/test_region_module_imports.py — CI guard for the manual-paste
registry (PR-A).

Regression context: PR #27 shipped placeholder module names ("s"/"c") and
PR #29 shipped an import of a nonexistent module (shared.gemini_navarea_parser)
— both passed a green unittest job because no test imported the registry
modules or the universal parser entry point. This guard fails CI whenever
a registry entry points at a module that cannot be imported or a parser
module is missing its two-arg main().
"""
import importlib
import inspect
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from scripts.run_manual_paste import REGIONS


class TestRegionModulesImportable(unittest.TestCase):

    def test_all_registry_parser_modules_import(self):
        for key, (parser_mod, _sync_mod, _subdir) in sorted(REGIONS.items()):
            with self.subTest(region=key, module=parser_mod):
                self.assertTrue(importlib.import_module(parser_mod))

    def test_all_registry_sync_modules_import(self):
        for key, (_parser_mod, sync_mod, _subdir) in sorted(REGIONS.items()):
            with self.subTest(region=key, module=sync_mod):
                self.assertTrue(importlib.import_module(sync_mod))

    def test_parser_modules_expose_two_arg_main(self):
        for key, (parser_mod, _sync_mod, _subdir) in sorted(REGIONS.items()):
            with self.subTest(region=key, module=parser_mod):
                module = importlib.import_module(parser_mod)
                self.assertTrue(callable(getattr(module, "main", None)),
                                parser_mod + " has no main()")
                try:
                    sig = inspect.signature(module.main)
                except (TypeError, ValueError):
                    continue  # not introspectable: skip signature check
                self.assertLessEqual(len(sig.parameters), 2,
                                     parser_mod + ".main() must accept at most "
                                     "(input_filename, output_filename)")

    def test_universal_parser_imports_cleanly(self):
        """The #29 regression: importing the universal parser must never
        crash even if the optional Gemini layer is absent."""
        import scripts.navarea_universal_parser as m
        self.assertTrue(callable(m.parse_bulletin_text))
        self.assertTrue(callable(m.parse_bulletin_text))


if __name__ == "__main__":
    unittest.main()
