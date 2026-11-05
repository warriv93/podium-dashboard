"""Tests for the seasonal layer's calendar, run in Node: which season a day falls in, what its chip says, and the key a
snooze is stored under."""
import json
import os
import subprocess
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEASON = os.path.join(ROOT, "podium_dashboard", "season", "season.js")


def ask(expr):
    """`expr` evaluated in Node with the season module as `S` and `day(y, m, d)` making a local noon date."""
    script = f"const S = require({json.dumps(SEASON)}); const day = (y, m, d) => new Date(y, m - 1, d, 12); console.log(JSON.stringify({expr}));"
    return json.loads(subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout)


class Calendar(unittest.TestCase):
    def test_christmas_runs_from_the_first_of_december_to_twelfth_night_with_lucia_and_new_year_inside_it(self):
        days = [(2026, 11, 30), (2026, 12, 1), (2026, 12, 12), (2026, 12, 13), (2026, 12, 14), (2026, 12, 24), (2026, 12, 30),
                (2026, 12, 31), (2027, 1, 1), (2027, 1, 2), (2027, 1, 6), (2027, 1, 7), (2027, 6, 1)]
        got = ask("[" + ", ".join(f"S.seasonOn(day({y}, {m}, {d}))" for y, m, d in days) + "]")
        self.assertEqual(got, [None, "xmas", "xmas", "lucia", "xmas", "xmas", "xmas", "newyear", "newyear", "xmas", "xmas", None, None])

    def test_the_chip_counts_down_to_christmas_eve_then_greets(self):
        days = [("xmas", 2026, 12, 1), ("xmas", 2026, 12, 23), ("xmas", 2026, 12, 24), ("xmas", 2026, 12, 26), ("xmas", 2027, 1, 3),
                ("lucia", 2026, 12, 13), ("newyear", 2026, 12, 31), ("newyear", 2027, 1, 1)]
        got = ask("[" + ", ".join(f'S.chipFor("{k}", day({y}, {m}, {d}))' for k, y, m, d in days) + "]")
        self.assertEqual(got, ["🎄 23 days to Christmas Eve", "🎄 Christmas Eve tomorrow", "🎅 God jul!", "🎄 God jul!",
                               "✨ God fortsättning", "🕯️ Glad Lucia", "🎆 Gott nytt år!", "🎆 Gott nytt år!"])

    def test_a_snooze_holds_for_the_rest_of_that_season_and_comes_back_next_year(self):
        got = ask('[S.snoozeKey("xmas", day(2026, 12, 2)), S.snoozeKey("xmas", day(2027, 1, 5)), S.snoozeKey("newyear", day(2027, 1, 1)),'
                  ' S.snoozeKey("lucia", day(2026, 12, 13)), S.snoozeKey("xmas", day(2027, 12, 2))]')
        self.assertEqual(got, ["xmas-2026", "xmas-2026", "newyear-2026", "lucia-2026", "xmas-2027"])

    def test_a_forced_season_wins_over_the_date_and_off_shows_none(self):
        got = ask('[S.pick(day(2026, 6, 1), "xmas"), S.pick(day(2026, 12, 5), "off"), S.pick(day(2026, 12, 5), "nope"),'
                  ' S.pick(day(2026, 12, 5), null), S.pick(day(2026, 6, 1), "__proto__")]')
        self.assertEqual(got, ["xmas", None, "xmas", "xmas", None])


if __name__ == "__main__":
    unittest.main()
