from apply_pilot.db import Posting, connect, upsert


def P(**kw):
    base = dict(source="greenhouse", board="acme", external_id="1", company="Acme",
                title="Software Engineer Intern", url="https://x.test/1", location="New York, NY")
    base.update(kw)
    return Posting(**base)


def test_upsert_dedupes_by_id_and_cross_source_key(tmp_path):
    conn = connect(tmp_path / "t.db")
    assert upsert(conn, [P()]) == (1, 0)
    assert upsert(conn, [P()]) == (0, 1)  # same id
    # same job seen on the GitHub list with different punctuation/case
    assert upsert(conn, [P(source="github", board="simplify", external_id="z",
                           company="ACME", title="Software Engineer, Intern",
                           location="New York NY")]) == (0, 1)
    assert upsert(conn, [P(external_id="2", title="Data Engineer")]) == (1, 0)
    assert conn.execute("SELECT count(*) FROM postings").fetchone()[0] == 2
