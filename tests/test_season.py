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


    def test_fettisdagen_has_no_snow_and_semlor_fly_by_often(self):
        got = ask('[S.SEASONS.fettisdagen.particles, S.SEASONS.fettisdagen.cap, S.SEASONS.fettisdagen.flyer.every <= 30]')
        self.assertEqual(got, [None, None, True])

    def test_halloween_easter_fettisdagen_and_valborg_fall_on_their_days(self):
        days = [(2026, 10, 23), (2026, 10, 24), (2026, 10, 31), (2026, 11, 1), (2026, 11, 2),
                (2026, 3, 28), (2026, 3, 29), (2026, 4, 5), (2026, 4, 6), (2026, 4, 7), (2027, 3, 21), (2027, 3, 29), (2027, 3, 30),
                (2026, 2, 14), (2026, 2, 15), (2026, 2, 17), (2026, 2, 18), (2027, 2, 9), (2027, 2, 10),
                (2026, 4, 27), (2026, 4, 28), (2026, 4, 30), (2026, 5, 1)]
        got = ask("[" + ", ".join(f"S.seasonOn(day({y}, {m}, {d}))" for y, m, d in days) + "]")
        self.assertEqual(got, [None, "halloween", "halloween", "halloween", None,
                               None, "easter", "easter", "easter", None, "easter", "easter", None,
                               None, "fettisdagen", "fettisdagen", None, "fettisdagen", None,
                               None, "valborg", "valborg", None])

    def test_the_new_seasons_count_down_then_greet(self):
        days = [("halloween", 2026, 10, 24), ("halloween", 2026, 10, 30), ("halloween", 2026, 10, 31), ("halloween", 2026, 11, 1),
                ("easter", 2026, 3, 29), ("easter", 2026, 4, 3), ("easter", 2026, 4, 4), ("easter", 2026, 4, 6),
                ("fettisdagen", 2026, 2, 15), ("fettisdagen", 2026, 2, 16), ("fettisdagen", 2026, 2, 17),
                ("valborg", 2026, 4, 28), ("valborg", 2026, 4, 29), ("valborg", 2026, 4, 30)]
        got = ask("[" + ", ".join(f'S.chipFor("{k}", day({y}, {m}, {d}))' for k, y, m, d in days) + "]")
        self.assertEqual(got, ["🎃 7 days to Halloween", "🎃 Halloween tomorrow", "🎃 Happy Halloween", "🎃 Happy Halloween",
                               "🐣 7 days to Easter", "🐣 2 days to Easter", "🐣 Glad påsk!", "🐣 Glad påsk!",
                               "🧁 2 days to Fettisdagen", "🧁 1 day to Fettisdagen", "🧁 Glad fettisdag!",
                               "🔥 2 days to Valborg", "🔥 1 day to Valborg", "🔥 Glad Valborg!"])

    def test_landings_are_celebrated_by_the_page_which_asks_the_season_for_its_marks(self):
        code = open(SEASON).read()
        self.assertIn("window.podiumSeason = { burst: () => (snoozed() ? null : season.burst) };", code)
        self.assertNotIn("watchLandings", code)

if __name__ == "__main__":
    unittest.main()
