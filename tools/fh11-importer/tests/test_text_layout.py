import sys
import unittest
from unittest.mock import patch

from text_layout import freehand_font, saved_line_runs


class FreeHandTextTests(unittest.TestCase):
    def test_saved_rows_keep_one_story_and_preserve_hard_breaks(self):
        runs = [{'text': 'One Two\nThree', 'style': {'size': 10}}]
        rows = [
            {'start': 0, 'length': 4, 'y': 100},
            {'start': 4, 'length': 4, 'y': 89},
            {'start': 8, 'length': 6, 'y': 77},
        ]
        result = saved_line_runs(runs, rows)
        self.assertEqual(''.join(run['text'] for run in result), 'One \u2028Two\nThree')
        self.assertEqual(result[-1]['style']['leading'], 12)
        self.assertEqual(runs, [{'text': 'One Two\nThree', 'style': {'size': 10}}])

    @patch.object(sys, 'platform', 'win32')
    def test_windows_uses_the_narrow_face(self):
        self.assertEqual(freehand_font('Arial Narrow', False, False), ('Arial', 'Narrow'))
        self.assertEqual(freehand_font('Arial Narrow', True, True), ('Arial', 'Narrow Bold Italic'))

    def test_bookman_family_uses_its_light_face(self):
        self.assertEqual(freehand_font('BookmanITC Lt BT', False, False), ('BookmanITC Lt BT', 'Light'))
