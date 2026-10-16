import json

from booking import corpus
from booking.generator import SCALES, reference


def files(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_corpus_seed(tmp_path):
    for name, seed in (("a", 7), ("b", 7), ("c", 8)):
        corpus.write(tmp_path / name, seed, "small")
    first, again, other = (files(tmp_path / name) for name in "abc")
    assert first == again
    assert len(first) == 2 * SCALES["small"].hotels
    assert first.keys() != other.keys()


def test_corpus_metadata_size(tmp_path):
    """Bedrock keeps at most 1 KB and 35 keys of custom metadata per vector in S3 Vectors."""
    corpus.write(tmp_path, 7, "small")
    hotels = {h["hotel_id"]: h for h in reference(7, SCALES["small"])["hotels"]}
    sidecars = sorted((tmp_path / "hotels").glob("*.md.metadata.json"))
    assert len(sidecars) == len(hotels)
    for sidecar in sidecars:
        raw = sidecar.read_bytes()
        attributes = json.loads(raw)["metadataAttributes"]
        assert len(raw) < 1024 and len(attributes) <= 35
        hotel = hotels[sidecar.name.removesuffix(".md.metadata.json")]
        assert attributes == {k: hotel[k] for k in ("hotel_id", "city", "country")}


def test_corpus_text_names_the_hotel_and_its_city():
    hotel = reference(7, SCALES["small"])["hotels"][0]
    text, _ = corpus.document(7, hotel)
    assert text.startswith(f"# {hotel['name']}\n") and hotel["city"] in text
    assert text.count("/5. ") == corpus.REVIEWS_PER_HOTEL
