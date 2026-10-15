"""Builders for Burp "Save items" XML and Record objects used across tests."""
import base64

from burpweb.burp_xml import Record

DOCTYPE = """<!DOCTYPE items [
<!ELEMENT items (item*)>
<!ATTLIST items burpVersion CDATA "">
<!ATTLIST items exportTime CDATA "">
<!ELEMENT item (time, url, host, port, protocol, method, path, extension, request, status, responselength, mimetype, response, comment)>
]>"""


def _message(tag: str, data: bytes, b64: bool) -> str:
    if b64:
        text = base64.b64encode(data).decode("ascii")
        return f'<{tag} base64="true"><![CDATA[{text}]]></{tag}>'
    return f'<{tag} base64="false"><![CDATA[{data.decode("utf-8")}]]></{tag}>'


def make_item(
    *,
    request: bytes,
    response: bytes | None,
    host: str = "example.com",
    port: int = 443,
    protocol: str = "https",
    time: str = "Wed Oct 15 10:00:00 UTC 2026",
    b64: bool = True,
) -> str:
    """One <item>. response=None omits the <response> element entirely."""
    resp = _message("response", response, b64) if response is not None else ""
    return (
        f"<item><time>{time}</time><url><![CDATA[{protocol}://{host}]]></url>"
        f'<host ip="127.0.0.1">{host}</host><port>{port}</port>'
        f"<protocol>{protocol}</protocol>"
        f"{_message('request', request, b64)}<status></status>{resp}</item>"
    )


def make_xml(items: list[str]) -> str:
    return (
        '<?xml version="1.0"?>\n'
        f"{DOCTYPE}\n"
        '<items burpVersion="2026.9" exportTime="Wed Oct 15 10:00:00 UTC 2026">\n'
        + "\n".join(items)
        + "\n</items>\n"
    )


def make_record(
    index: int,
    *,
    method: str = "GET",
    path: str = "/",
    query: str = "",
    body: bytes = b"",
    content_type: str = "",
    status: int = 200,
    scheme: str = "https",
    host: str = "example.com",
    port: int = 443,
    headers: tuple[tuple[str, str], ...] = (("Content-Type", "text/plain"),),
    response_body: bytes = b"",
) -> Record:
    return Record(
        index=index,
        time="",
        scheme=scheme,
        host=host,
        port=port,
        method=method,
        path=path,
        query=query,
        request_body=body,
        request_content_type=content_type,
        status=status,
        response_headers=headers,
        response_body=response_body or f"record {index}".encode(),
    )
