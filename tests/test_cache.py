import pytest

from enricher.cache import Cache


def make_clock(start: float = 1_700_000_000.0):
    state = {"t": start}

    def clock() -> float:
        return state["t"]

    def advance(seconds: float) -> None:
        state["t"] += seconds

    clock.advance = advance  # type: ignore[attr-defined]
    return clock


@pytest.fixture
def cache():
    c = Cache(":memory:", clock=make_clock())
    yield c
    c.close()


def test_get_anchors_devolve_none_quando_ausente(cache):
    assert cache.get_anchors("nope") is None


def test_anchors_round_trip(cache):
    anchors = [
        {"section_path": ["X"], "concept": "foo", "visual_type": "diagram"},
        {"section_path": ["Y"], "concept": "bar", "visual_type": "histology"},
    ]
    cache.put_anchors("sha1", anchors)
    assert cache.get_anchors("sha1") == anchors


def test_anchors_overwrite(cache):
    cache.put_anchors("k", [{"a": 1}])
    cache.put_anchors("k", [{"a": 2}])
    assert cache.get_anchors("k") == [{"a": 2}]


def test_candidates_dentro_do_ttl():
    clock = make_clock()
    c = Cache(":memory:", clock=clock)
    payload = [{"image_url": "http://x", "title": "y"}]
    c.put_candidates("wikimedia", "serotonina", "diagram", payload)
    assert c.get_candidates("wikimedia", "serotonina", "diagram", ttl_days=30) == payload
    clock.advance(29 * 86400)
    assert c.get_candidates("wikimedia", "serotonina", "diagram", ttl_days=30) == payload
    c.close()


def test_candidates_expira_apos_ttl():
    clock = make_clock()
    c = Cache(":memory:", clock=clock)
    c.put_candidates("wikimedia", "q", "diagram", [{"a": 1}])
    clock.advance(31 * 86400)
    assert c.get_candidates("wikimedia", "q", "diagram", ttl_days=30) is None
    c.close()


def test_candidates_chave_composta_source_query_visualtype():
    c = Cache(":memory:", clock=make_clock())
    c.put_candidates("wikimedia", "q", "diagram", [{"a": 1}])
    c.put_candidates("wikimedia", "q", "histology", [{"b": 2}])
    c.put_candidates("openstax", "q", "diagram", [{"c": 3}])
    assert c.get_candidates("wikimedia", "q", "diagram", ttl_days=30) == [{"a": 1}]
    assert c.get_candidates("wikimedia", "q", "histology", ttl_days=30) == [{"b": 2}]
    assert c.get_candidates("openstax", "q", "diagram", ttl_days=30) == [{"c": 3}]
    c.close()


def test_candidates_overwrite_renova_timestamp():
    clock = make_clock()
    c = Cache(":memory:", clock=clock)
    c.put_candidates("wikimedia", "q", "diagram", [{"a": 1}])
    clock.advance(20 * 86400)
    c.put_candidates("wikimedia", "q", "diagram", [{"a": 2}])  # renova
    clock.advance(15 * 86400)  # 15d desde a renovação, < 30
    assert c.get_candidates("wikimedia", "q", "diagram", ttl_days=30) == [{"a": 2}]
    c.close()


def test_get_image_devolve_none_quando_ausente(cache):
    assert cache.get_image("nope") is None


def test_images_round_trip_com_metadata(cache):
    cache.put_image(
        "sha1",
        filename="abc.webp",
        source="wikimedia",
        source_url="https://commons.wikimedia.org/wiki/File:X",
        width=1024,
        height=768,
        size_bytes=12345,
    )
    got = cache.get_image("sha1")
    assert got == {
        "sha": "sha1",
        "filename": "abc.webp",
        "source": "wikimedia",
        "source_url": "https://commons.wikimedia.org/wiki/File:X",
        "width": 1024,
        "height": 768,
        "bytes": 12345,
    }


def test_images_metadata_opcional_pode_ser_none(cache):
    cache.put_image("sha2", filename="b.png", source="openstax", source_url="u")
    got = cache.get_image("sha2")
    assert got["width"] is None and got["height"] is None and got["bytes"] is None


def test_persistencia_em_disco(tmp_path):
    db = tmp_path / "c.db"
    with Cache(db) as c:
        c.put_image("k", filename="a.webp", source="wikimedia", source_url="u")
        c.put_anchors("ns", [{"x": 1}])
    with Cache(db) as c:
        assert c.get_image("k")["filename"] == "a.webp"
        assert c.get_anchors("ns") == [{"x": 1}]


def test_url_index_round_trip(cache):
    assert cache.get_sha_for_url("https://x/y.png") is None
    cache.put_url_index("https://x/y.png", "sha123")
    assert cache.get_sha_for_url("https://x/y.png") == "sha123"


def test_url_index_overwrite(cache):
    cache.put_url_index("https://x/y.png", "sha_old")
    cache.put_url_index("https://x/y.png", "sha_new")
    assert cache.get_sha_for_url("https://x/y.png") == "sha_new"


def test_cria_diretorio_pai_se_necessario(tmp_path):
    db = tmp_path / "nested" / "subdir" / "c.db"
    with Cache(db) as c:
        c.put_anchors("k", [{"a": 1}])
    assert db.exists()
