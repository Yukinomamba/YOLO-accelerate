"""Protect evidence collection from stale zero counts or ignored logic changes."""
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools/pango'))
from collect_implementation import canonical_netlist, final_unrouted_count


class EvidenceTests(unittest.TestCase):
    def test_latest_count_wins_across_formats(self):
        text = 'Unrouted nets: 0\nUnrouted nets at iteration 38 (0.220 sec): 3\n'
        self.assertEqual(final_unrouted_count(text)[0], 3)
        self.assertEqual(final_unrouted_count(text+'Number of unrouted nets = 0\n')[0], 0)

    def test_no_completion_only_shortcut(self):
        with self.assertRaises(RuntimeError):
            final_unrouted_count("Design 'npu_measure_top' has been routed successfully.\n")
        self.assertEqual(final_unrouted_count('All nets are routed successfully\n')[0], 0)
        self.assertEqual(final_unrouted_count('Unrouted nets | 1,024\n')[0], 1024)

    def test_netlist_metadata_only(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'netlist.vm'
            path.write_text('// Generated at time A\n\t// SDC constraint : path A\nmodule x;\nassign q = 1;\nendmodule\n')
            reference = canonical_netlist(path)
            path.write_text('// Generated at time B\n\t// SDC constraint : path B\nmodule x;\nassign q = 1;\nendmodule\n')
            self.assertEqual(reference, canonical_netlist(path))
            path.write_text('module x;\nassign q = 0;\nendmodule\n')
            self.assertNotEqual(reference, canonical_netlist(path))


if __name__ == '__main__':
    unittest.main()
