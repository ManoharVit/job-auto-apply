import hashlib

from workbench.cli import main


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(capsys, *argv):
    code = main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def test_stats(legacy_db, capsys):
    code, out, _ = run(capsys, "--db", str(legacy_db), "stats")
    assert code == 0
    assert "Read-only" in out
    assert "Unconfirmed" in out and "3" in out
    assert "Not applied" in out
    assert "Applied successfully" not in out


def test_list_filters(legacy_db, capsys):
    code, out, _ = run(capsys, "--db", str(legacy_db), "list", "--platform", "naukri",
                       "--status", "unconfirmed")
    assert code == 0
    assert "Databricks Data Engineer" in out
    assert "Python Backend Developer" not in out
    assert "1 of 9 jobs" in out


def test_list_search_no_matches(legacy_db, capsys):
    code, out, _ = run(capsys, "--db", str(legacy_db), "list", "--search", "zzz")
    assert code == 0
    assert "No jobs match" in out


def test_list_limit(legacy_db, capsys):
    code, out, _ = run(capsys, "--db", str(legacy_db), "list", "--limit", "2")
    assert code == 0
    assert "showing 2" in out


def test_show_existing(legacy_db, capsys):
    code, out, _ = run(capsys, "--db", str(legacy_db), "show", "1")
    assert code == 0
    assert "Python Backend Developer" in out
    assert "never verified" in out
    assert "https://www.linkedin.com/jobs/view/111" in out
    assert "open it yourself" in out.lower()


def test_show_missing_id(legacy_db, capsys):
    code, _, err = run(capsys, "--db", str(legacy_db), "show", "999")
    assert code == 1
    assert "No job with id 999" in err


def test_duplicates(legacy_db, capsys):
    code, out, _ = run(capsys, "--db", str(legacy_db), "duplicates")
    assert code == 0
    assert "Same link" in out
    assert "Same title + company" in out


def test_bad_db_path(tmp_path, capsys):
    code, _, err = run(capsys, "--db", str(tmp_path / "missing.db"), "stats")
    assert code == 2
    assert "not found" in err


def test_no_command_shows_help(legacy_db, capsys):
    code, out, _ = run(capsys, "--db", str(legacy_db))
    assert code == 2
    assert "stats" in out


def test_every_command_leaves_db_bytes_unchanged(legacy_db, capsys):
    before = sha256(legacy_db)
    for argv in (["stats"], ["list"], ["show", "3"], ["duplicates"]):
        run(capsys, "--db", str(legacy_db), *argv)
    assert sha256(legacy_db) == before
