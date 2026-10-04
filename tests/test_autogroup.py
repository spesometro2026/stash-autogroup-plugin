"""Offline tests: no Stash needed. Run with: python3 -m unittest discover -s tests"""
import os
import sys
import types
import unittest

# autoGroup imports stashapi at module level; stub it so tests run without the dependency.
log_stub = types.SimpleNamespace(info=lambda *a, **k: None, warning=lambda *a, **k: None,
                                 error=lambda *a, **k: None)
stashapi = types.ModuleType("stashapi")
stashapi.log = log_stub
stashapp = types.ModuleType("stashapi.stashapp")
stashapp.StashInterface = object
sys.modules.update({"stashapi": stashapi, "stashapi.log": log_stub, "stashapi.stashapp": stashapp})
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import autoGroup  # noqa: E402

RULES = autoGroup.compile_rules(autoGroup.DEFAULT_RULES)


def match(name):
    return autoGroup.match_rule(RULES, name)


class DefaultRules(unittest.TestCase):
    def test_scene_and_part_become_separate_groups_with_part_as_index(self):
        self.assertEqual(match("Eden's Dream - Scene 1 - Part 1 - HogTaped.mp4"), ("Eden's Dream - Scene 1", 1))
        self.assertEqual(match("Eden's Dream - Scene 1 - Part 3 - The Gags.mp4"), ("Eden's Dream - Scene 1", 3))
        self.assertEqual(match("Eden's Dream - Scene 2 - SpreadEagle - Part 2.mp4"), ("Eden's Dream - Scene 2", 2))

    def test_no_duplicate_indexes_within_a_group(self):
        files = ["Eden's Dream - Scene 1 - Part 1 - A.mp4", "Eden's Dream - Scene 1 - Part 2 - B.mp4",
                 "Eden's Dream - Scene 1 - Part 3 - C.mp4", "Eden's Dream - Scene 2 - X - Part 1.mp4",
                 "Eden's Dream - Scene 2 - X - Part 2.mp4"]
        seen = {}
        for f in files:
            name, idx = match(f)
            seen.setdefault(name, []).append(idx)
        for name, idxs in seen.items():
            self.assertEqual(len(idxs), len(set(idxs)), name)

    def test_en_dash_separator_does_not_leave_trailing_dash(self):
        self.assertEqual(match("The Chains Of Andromeda – Part 3.mp4"), ("The Chains Of Andromeda", 3))
        self.assertEqual(match("The Chains Of Andromeda — Part 1.mp4"), ("The Chains Of Andromeda", 1))

    def test_episode_forms(self):
        self.assertEqual(match("Hookup Hotshot Episode 453 - Shrooms Q.mp4"), ("Hookup Hotshot", 453))
        self.assertEqual(match("Hookup Hotshot - Episode 450 - Iris Leon.mp4"), ("Hookup Hotshot", 450))
        self.assertEqual(match("Futile Struggles - Elle Mckenzie In The Evaluation - Episode 10.mp4"),
                         ("Futile Struggles - Elle Mckenzie In The Evaluation", 10))

    def test_part_forms(self):
        self.assertEqual(match("INFERNAL RESTRAINTS - Queen of Pain Part 2 - Elise Graves PD.mp4"),
                         ("INFERNAL RESTRAINTS - Queen of Pain", 2))
        self.assertEqual(match("Insex - Farm Brat pt. 2 starring 62 & 912.mp4"), ("Insex - Farm Brat", 2))
        self.assertEqual(match("XXXFILE.ORG-fs_cupcakestest_part2.mp4"), ("XXXFILE.ORG-fs_cupcakestest", 2))
        self.assertEqual(match("Preparing Dixie Comet for Transport - Part 1.mp4"),
                         ("Preparing Dixie Comet for Transport", 1))

    def test_feat_form(self):
        self.assertEqual(match("Insex - Twisted Flower 2 feat. Violet.mp4"), ("Insex - Twisted Flower", 2))

    def test_day_with_scene_number_groups_by_day_and_indexes_by_scene(self):
        for n in (1, 2, 3):
            self.assertEqual(match(f"[BDSM] 50 Shades Of Veronica Avluv Day 3 (Scene {n}).mp4"),
                             ("[BDSM] 50 Shades Of Veronica Avluv - Day 3", n))
        self.assertEqual(match("Some Show Day 2.mp4"), ("Some Show", 2))

    def test_scene_without_part_still_uses_the_generic_rule(self):
        self.assertEqual(match("Some Title Scene 3.mp4"), ("Some Title", 3))

    def test_untouched_filenames_stay_unmatched(self):
        self.assertEqual(match("Doubled 1 - Studio - Performer.mp4"), (None, None))
        self.assertEqual(match("2024-05-01 random clip.mp4"), (None, None))


class FakeStash:
    """Serves one page of scenes, records mutations; lets run() execute without Stash."""

    def __init__(self, scenes, settings):
        self.scenes, self.settings, self.created, self.updated = scenes, settings, [], []

    def get_configuration(self):
        return {"plugins": {"autoGroup": self.settings}}

    def call_GQL(self, query, variables=None):
        if "findScenes" in query:
            return {"findScenes": {"count": len(self.scenes), "scenes": self.scenes if variables["page"] == 1 else []}}
        if "findGroups" in query:
            return {"findGroups": {"groups": []}}
        if "groupCreate" in query:
            self.created.append(variables["input"]["name"])
            return {"groupCreate": {"id": f"g{len(self.created)}"}}
        if "sceneUpdate" in query:
            self.updated.append(variables["input"])
            return {"sceneUpdate": {"id": variables["input"]["id"]}}
        raise AssertionError(query)


def scene(sid, path, groups=None):
    return {"id": sid, "groups": groups or [], "files": [{"path": path}]}


class RunBehaviour(unittest.TestCase):
    def test_dry_run_writes_nothing(self):
        st = FakeStash([scene("1", "/x/Show - Episode 1.mp4"), scene("2", "/x/Show - Episode 2.mp4")],
                       {"dryRun": True})
        autoGroup.run(st)
        self.assertEqual((st.created, st.updated), ([], []))

    def test_single_match_does_not_create_a_group(self):
        st = FakeStash([scene("1", "/x/Show - Episode 1.mp4")], {"dryRun": False})
        autoGroup.run(st)
        self.assertEqual((st.created, st.updated), ([], []))

    def test_two_matches_create_one_group_with_indexes(self):
        st = FakeStash([scene("1", "/x/Show - Episode 1.mp4"), scene("2", "/x/Show - Episode 2.mp4")],
                       {"dryRun": False})
        autoGroup.run(st)
        self.assertEqual(st.created, ["Show"])
        self.assertEqual([(u["id"], u["groups"][-1]["scene_index"]) for u in st.updated], [("1", 1), ("2", 2)])

    def test_other_groups_keep_their_scene_index(self):
        other = [{"group": {"id": "77"}, "scene_index": 5}]
        st = FakeStash([scene("1", "/x/Show - Episode 1.mp4", other), scene("2", "/x/Show - Episode 2.mp4")],
                       {"dryRun": False, "onlyUngrouped": False})
        autoGroup.run(st)
        first = [u for u in st.updated if u["id"] == "1"][0]["groups"]
        self.assertIn({"group_id": "77", "scene_index": 5}, first)


if __name__ == "__main__":
    unittest.main()
