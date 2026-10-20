from datetime import UTC, datetime, timedelta

from procurement.sources import supplier_serp_browser as b
from procurement.sources.supplier_captcha_recovery import file_sha, issue_retry, pacing_paths
from procurement.sources.supplier_serp import SearchEngine, build_supplier_query

QUERY = build_supplier_query("Бумага офисная")


def setup(tmp_path):
    profile = b.profile_directory(tmp_path, "tenant-a", SearchEngine.GOOGLE)
    b._private_dir(profile)
    now = datetime.now(UTC)
    b._mark(tmp_path, profile, SearchEngine.GOOGLE, "BLOCKED", now)
    paths = pacing_paths(tmp_path, profile, SearchEngine.GOOGLE)
    return profile, paths, now


def test_retry_is_single_use_without_erasing_global_hold(tmp_path):
    profile, paths, now = setup(tmp_path)
    snapshots = tuple(file_sha(p) for p in paths)
    issue_retry(tmp_path, profile, SearchEngine.GOOGLE, QUERY, "session", snapshots)
    assert b._reserve(tmp_path, profile, SearchEngine.GOOGLE, datetime.now(UTC), QUERY)
    assert not (profile / "human-retry.json").exists()
    assert b._state(paths[0], "global:" + paths[0].stem)[1] > now
    assert not b._reserve(
        tmp_path, profile, SearchEngine.GOOGLE, now + timedelta(seconds=40), QUERY
    )


def test_wrong_query_cannot_consume_a_valid_grant_for_access(tmp_path):
    profile, paths, now = setup(tmp_path)
    issue_retry(
        tmp_path, profile, SearchEngine.GOOGLE, QUERY, "session", tuple(file_sha(p) for p in paths)
    )
    assert not b._reserve(
        tmp_path, profile, SearchEngine.GOOGLE, now, build_supplier_query("Другое")
    )
    assert not b._reserve(tmp_path, profile, SearchEngine.GOOGLE, now, QUERY)


def test_later_origin_block_invalidates_grant(tmp_path):
    profile, paths, now = setup(tmp_path)
    snapshots = tuple(file_sha(p) for p in paths)
    issue_retry(tmp_path, profile, SearchEngine.GOOGLE, QUERY, "session", snapshots)
    b._mark(tmp_path, profile, SearchEngine.GOOGLE, "BLOCKED", now + timedelta(seconds=1))
    assert not b._reserve(tmp_path, profile, SearchEngine.GOOGLE, now + timedelta(seconds=2), QUERY)


def test_pacing_still_blocks_and_does_not_spend_grant(tmp_path):
    profile, paths, now = setup(tmp_path)
    global_scope = "global:" + paths[0].stem
    b._write_state(paths[0], global_scope, now + timedelta(seconds=15), now + timedelta(hours=1))
    issue_retry(
        tmp_path, profile, SearchEngine.GOOGLE, QUERY, "session", tuple(file_sha(p) for p in paths)
    )
    assert not b._reserve(tmp_path, profile, SearchEngine.GOOGLE, now, QUERY)
    assert (profile / "human-retry.json").exists()
    assert b._reserve(tmp_path, profile, SearchEngine.GOOGLE, now + timedelta(seconds=16), QUERY)
