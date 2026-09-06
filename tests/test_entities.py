"""HTML entities in caption text are decoded, after cue tags are stripped."""
import ytscribe


def _write(tmp_path, body):
    p = tmp_path / "abc123.en.vtt"
    p.write_text("WEBVTT\nKind: captions\nLanguage: en\n\n" + body, encoding="utf-8")
    return str(p)


def test_speaker_change_markers_are_decoded(tmp_path):
    vtt = _write(tmp_path, "00:00:00.000 --> 00:00:02.000\n&gt;&gt; Yeah, it is wild &amp; loud.\n")
    entries = ytscribe._parse_vtt_entries(vtt)
    assert [e[2] for e in entries] == [">> Yeah, it is wild & loud."]


def test_numeric_entities_and_quotes(tmp_path):
    vtt = _write(tmp_path, "00:00:00.000 --> 00:00:02.000\nit&#39;s &quot;fine&quot;\n")
    entries = ytscribe._parse_vtt_entries(vtt)
    assert entries[0][2] == "it's \"fine\""


def test_tags_are_stripped_before_decoding(tmp_path):
    """An entity that decodes to angle brackets must survive; a real cue tag must not."""
    vtt = _write(tmp_path, "00:00:00.000 --> 00:00:02.000\n<c>a &lt;b&gt; c</c>\n")
    entries = ytscribe._parse_vtt_entries(vtt)
    assert entries[0][2] == "a <b> c"


def test_decoded_duplicates_still_dedupe(tmp_path):
    vtt = _write(
        tmp_path,
        "00:00:00.000 --> 00:00:02.000\n&gt;&gt; hello\n\n00:00:02.000 --> 00:00:04.000\n>> hello\n",
    )
    entries = ytscribe._parse_vtt_entries(vtt)
    assert len(entries) == 1
