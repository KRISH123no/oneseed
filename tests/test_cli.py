from oneseed.cli import main


def test_list_names_the_scenarios(capsys):
    assert main(["list"]) == 0
    out = capsys.readouterr().out
    assert "lease " in out and "lease-fixed" in out and "raft-votes-twice" in out


def test_search_reports_failing_seeds_and_exits_nonzero(capsys):
    assert main(["search", "lease", "--seeds", "40"]) == 1
    out = capsys.readouterr().out
    assert "of 40 seeds fail" in out and "at most one lock holder" in out
    assert "next: oneseed shrink lease" in out


def test_search_on_the_fixed_version_exits_zero(capsys):
    assert main(["search", "lease-fixed", "--seeds", "40"]) == 0
    assert "0 of 40 seeds fail" in capsys.readouterr().out


def test_replay_proves_the_run_is_repeatable(capsys):
    assert main(["replay", "lease", "4"]) == 1
    out = capsys.readouterr().out
    assert "ran twice, same trace both times" in out
    assert "VIOLATION" in out
    assert main(["replay", "lease-fixed", "4"]) == 0
    assert "no invariant was broken" in capsys.readouterr().out


def test_shrink_prints_the_faults_that_are_needed(capsys):
    assert main(["shrink", "lease", "4"]) == 1
    out = capsys.readouterr().out
    assert "replaying them from a list gives the identical trace" in out
    assert "shrunk to 1 in" in out and "Every one of these is needed" in out
    assert "Granted #0 from 0 to 1 held for" in out


def test_shrinking_a_passing_seed_says_so(capsys):
    assert main(["shrink", "lease-fixed", "4"]) == 0
    assert "nothing to shrink" in capsys.readouterr().out
