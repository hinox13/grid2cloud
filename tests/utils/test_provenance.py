import hashlib
import json

from cloud2grid.utils import provenance


def test_hash_tree_file_and_directory(tmp_path):
    f = tmp_path / "a.txt"
    f.write_bytes(b"hello")
    sha, size, n = provenance.hash_tree(f)
    assert sha == hashlib.sha256(b"hello").hexdigest()
    assert (size, n) == (5, 1)

    d = tmp_path / "tree"
    (d / "sub").mkdir(parents=True)
    (d / "x.bin").write_bytes(b"1")
    (d / "sub" / "y.bin").write_bytes(b"22")
    (d / ".cache").mkdir()
    (d / ".cache" / "ignored").write_bytes(b"zzz")
    sha1, size1, n1 = provenance.hash_tree(d)
    assert (size1, n1) == (3, 2)

    (d / "sub" / "y.bin").write_bytes(b"23")
    assert provenance.hash_tree(d)[0] != sha1


def test_record_upserts_manifest(tmp_path):
    data = tmp_path / "data.csv"
    data.write_text("a,b\n1,2\n")
    manifest = tmp_path / "prov.json"

    entry = provenance.record(
        data,
        source_id="src",
        url="https://example.org",
        licence="CC-BY-4.0",
        manifest_path=manifest,
    )
    assert entry["size_bytes"] == data.stat().st_size
    assert entry["sha256"] == provenance.sha256_file(data)

    data.write_text("a,b\n1,3\n")
    provenance.record(
        data,
        source_id="src",
        url="https://example.org",
        licence="CC-BY-4.0",
        manifest_path=manifest,
    )
    stored = json.loads(manifest.read_text())
    assert len(stored) == 1
    assert next(iter(stored.values()))["sha256"] == provenance.sha256_file(data)
