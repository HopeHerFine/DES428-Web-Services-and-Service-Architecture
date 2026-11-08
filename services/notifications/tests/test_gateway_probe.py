import http.cookiejar
from urllib.request import Request

from app.smoke_gateway import LocalhostBrowserCookiePolicy


def test_secure_cookie_exception_is_limited_to_local_test_origin():
    policy = LocalhostBrowserCookiePolicy()
    cookie = http.cookiejar.Cookie(
        version=0, name="AUTH_SESSION_ID", value="test-only", port=None, port_specified=False,
        domain="localhost.local", domain_specified=False, domain_initial_dot=False,
        path="/auth/", path_specified=True, secure=True, expires=None, discard=True,
        comment=None, comment_url=None, rest={}, rfc2109=False,
    )
    assert policy.return_ok_secure(cookie, Request("http://localhost:8080/auth/"))
    assert not policy.return_ok_secure(cookie, Request("http://localhost:9000/auth/"))
    assert not policy.return_ok_secure(cookie, Request("http://other.example:8080/auth/"))
    assert not policy.return_ok_secure(cookie, Request("http://localhost.evil.test:8080/auth/"))
    assert policy.return_ok_secure(cookie, Request("https://other.example/auth/"))
    assert cookie.secure is True


def test_cookie_jar_actually_sends_secure_login_cookie_on_localhost():
    jar = http.cookiejar.CookieJar(policy=LocalhostBrowserCookiePolicy())
    cookie = http.cookiejar.Cookie(
        version=0, name="KC_RESTART", value="test-only", port=None, port_specified=False,
        domain="localhost.local", domain_specified=False, domain_initial_dot=False,
        path="/auth/realms/homeservice/", path_specified=True, secure=True,
        expires=None, discard=True, comment=None, comment_url=None, rest={}, rfc2109=False,
    )
    jar.set_cookie(cookie)
    local = Request("http://localhost:8080/auth/realms/homeservice/login-actions/authenticate")
    jar.add_cookie_header(local)
    assert local.get_header("Cookie") == "KC_RESTART=test-only"
    other_port = Request("http://localhost:9000/auth/realms/homeservice/login-actions/authenticate")
    jar.add_cookie_header(other_port)
    assert other_port.get_header("Cookie") is None
