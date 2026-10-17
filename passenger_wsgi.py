"""Passenger WSGI entry point for cPanel.

The Telegram polling worker runs separately. This small WSGI app forwards web
requests to the private aiohttp Mini App server started by that worker.
"""
from http import HTTPStatus
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


BACKEND = "http://127.0.0.1:8080"
HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailer", "transfer-encoding", "upgrade",
}


def application(environ, start_response):
    path = environ.get("PATH_INFO", "/") or "/"
    query = environ.get("QUERY_STRING", "")
    url = BACKEND + quote(path, safe="/%:@!$&'()*+,;=-._~")
    if query:
        url += "?" + query

    headers = {}
    for key, header in (
        ("HTTP_AUTHORIZATION", "Authorization"),
        ("HTTP_ORIGIN", "Origin"),
        ("HTTP_ACCEPT", "Accept"),
        ("HTTP_IF_NONE_MATCH", "If-None-Match"),
        ("HTTP_IF_MODIFIED_SINCE", "If-Modified-Since"),
        ("CONTENT_TYPE", "Content-Type"),
    ):
        value = environ.get(key)
        if value:
            headers[header] = value

    try:
        length = int(environ.get("CONTENT_LENGTH") or "0")
    except ValueError:
        length = 0
    body = environ["wsgi.input"].read(length) if length else None
    request = Request(url, data=body, headers=headers,
                      method=environ.get("REQUEST_METHOD", "GET"))
    try:
        try:
            response = urlopen(request, timeout=20)
        except HTTPError as error:
            response = error
        with response:
            status = response.status
            response_headers = [
                (name, value) for name, value in response.headers.items()
                if name.lower() not in HOP_BY_HOP
            ]
            payload = response.read()
    except (URLError, TimeoutError, OSError):
        status = HTTPStatus.SERVICE_UNAVAILABLE
        response_headers = [("Content-Type", "text/plain; charset=utf-8")]
        payload = b"The bot API is not running. Please try again shortly."

    phrase = HTTPStatus(status).phrase if status in HTTPStatus._value2member_map_ else "Unknown"
    start_response(f"{status} {phrase}", response_headers)
    return [payload]
