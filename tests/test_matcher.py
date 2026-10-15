from burpfixtures import make_record
from burpweb.matcher import Incoming, Matcher, Tier


def incoming(method="GET", path="/", query="", body=b"", content_type="", scheme="https", host="example.com", port=443):
    return Incoming(scheme, host, port, method, path, query, body, content_type)


def test_exact_match():
    rec = make_record(1, path="/a", query="x=1")
    assert Matcher([rec]).match(incoming(path="/a", query="x=1")) == (rec, Tier.EXACT)


def test_exact_prefers_most_recent_even_if_error():
    old = make_record(1, path="/a", status=200)
    new = make_record(2, path="/a", status=500)
    assert Matcher([old, new]).match(incoming(path="/a")) == (new, Tier.EXACT)


def test_query_order_insensitive():
    rec = make_record(1, path="/s", query="a=1&b=2&b=3")
    assert Matcher([rec]).match(incoming(path="/s", query="b=2&a=1&b=3"))[1] is Tier.EXACT


def test_form_body_order_insensitive():
    rec = make_record(1, method="POST", path="/f", body=b"a=1&b=2", content_type="application/x-www-form-urlencoded")
    req = incoming("POST", "/f", body=b"b=2&a=1", content_type="application/x-www-form-urlencoded; charset=UTF-8")
    assert Matcher([rec]).match(req) == (rec, Tier.EXACT)


def test_json_body_normalized():
    rec = make_record(1, method="POST", path="/j", body=b'{"a": 1, "b": [1, 2]}', content_type="application/json")
    req = incoming("POST", "/j", body=b'{"b":[1,2],"a":1}', content_type="application/vnd.api+json")
    assert Matcher([rec]).match(req) == (rec, Tier.EXACT)


def test_invalid_json_compared_as_raw_bytes():
    rec = make_record(1, method="POST", path="/j", body=b"{bad", content_type="application/json")
    m = Matcher([rec])
    assert m.match(incoming("POST", "/j", body=b"{bad", content_type="application/json"))[1] is Tier.EXACT
    assert m.match(incoming("POST", "/j", body=b"{bad ", content_type="application/json"))[1] is Tier.FALLBACK


def test_empty_body_ignores_content_type():
    rec = make_record(1, path="/e")
    req = incoming(path="/e", content_type="application/json")
    assert Matcher([rec]).match(req) == (rec, Tier.EXACT)


def test_fallback_prefers_latest_success():
    ok = make_record(1, path="/p", query="v=1", status=200)
    failed = make_record(2, path="/p", query="v=2", status=500)
    assert Matcher([ok, failed]).match(incoming(path="/p", query="v=3")) == (ok, Tier.FALLBACK)


def test_fallback_uses_latest_any_when_no_success():
    a = make_record(1, path="/p", query="v=1", status=404)
    b = make_record(2, path="/p", query="v=2", status=500)
    assert Matcher([a, b]).match(incoming(path="/p")) == (b, Tier.FALLBACK)


def test_fallback_ignores_body():
    rec = make_record(1, method="POST", path="/api", body=b'{"q":1}', content_type="application/json")
    req = incoming("POST", "/api", body=b'{"q":2}', content_type="application/json")
    assert Matcher([rec]).match(req) == (rec, Tier.FALLBACK)


def test_host_case_insensitive():
    rec = make_record(1, host="example.com")
    assert Matcher([rec]).match(incoming(host="Example.COM"))[1] is Tier.EXACT


def test_head_served_from_get():
    rec = make_record(1, path="/h")
    assert Matcher([rec]).match(incoming("HEAD", "/h")) == (rec, Tier.HEAD)


def test_captured_head_wins_over_get():
    get = make_record(1, path="/h")
    head = make_record(2, method="HEAD", path="/h")
    assert Matcher([get, head]).match(incoming("HEAD", "/h")) == (head, Tier.EXACT)


def test_full_response_preferred_over_later_304_or_206():
    full = make_record(1, path="/app.js", status=200)
    not_modified = make_record(2, path="/app.js", status=304)
    partial = make_record(3, path="/app.js", status=206)
    assert Matcher([full, not_modified, partial]).match(incoming(path="/app.js")) == (full, Tier.EXACT)


def test_fallback_full_response_beats_exact_304():
    full = make_record(1, path="/app.js", query="v=1", status=200)
    not_modified = make_record(2, path="/app.js", query="v=2", status=304)
    assert Matcher([full, not_modified]).match(incoming(path="/app.js", query="v=2")) == (full, Tier.FALLBACK)


def test_304_used_when_nothing_else_captured():
    not_modified = make_record(1, path="/app.js", status=304)
    m = Matcher([not_modified])
    assert m.match(incoming(path="/app.js")) == (not_modified, Tier.EXACT)
    assert m.match(incoming(path="/app.js", query="x=1")) == (not_modified, Tier.FALLBACK)


def test_misses():
    m = Matcher([make_record(1, path="/a")])
    assert m.match(incoming(path="/b")) == (None, Tier.MISS)
    assert m.match(incoming("POST", "/a")) == (None, Tier.MISS)
    assert m.match(incoming(path="/a", port=8443)) == (None, Tier.MISS)
    assert m.match(incoming(path="/a", scheme="http", port=443)) == (None, Tier.MISS)
