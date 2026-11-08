"""Exercise browser code+PKCE login, SSR inbox and ownership through nginx.

Transport connects to Docker's gateway while requests/cookies/redirects retain
the real public origin, just as a browser on the host would see them.
"""
import http.client
import http.cookiejar
import json
import os
import random
import time
from datetime import date, timedelta
from html.parser import HTMLParser
from urllib.error import HTTPError
from urllib.parse import urlencode, urlparse
from urllib.request import HTTPHandler, HTTPCookieProcessor, Request, build_opener

ORIGIN = "http://localhost:8080"
PASSWORD = "eDemand-2026!"  # Only the public, seeded demo accounts.


class LocalhostBrowserCookiePolicy(http.cookiejar.DefaultCookiePolicy):
    """Match browsers' secure-cookie exception for the one local test origin.

    urllib otherwise withholds Keycloak's Secure login cookies over HTTP even
    on localhost. Do not relax this for arbitrary hosts or change actual cookies.
    The transport independently restricts requests to this same origin.
    """
    def return_ok_secure(self, cookie, request):
        url = urlparse(request.full_url)
        if url.scheme == "http" and url.hostname == "localhost" and url.port == 8080:
            return True
        return super().return_ok_secure(cookie, request)


class GatewayHTTPHandler(HTTPHandler):
    def http_open(self, request):
        if urlparse(request.full_url).netloc != "localhost:8080":
            raise RuntimeError("Unexpected cross-origin redirect during login")
        return self.do_open(lambda host, timeout=30, **kwargs:
                            http.client.HTTPConnection(os.getenv("GATEWAY_CONNECT_HOST", "gateway"),
                                                       int(os.getenv("GATEWAY_CONNECT_PORT", "80")), timeout=timeout), request)


class LoginForm(HTMLParser):
    def __init__(self):
        super().__init__()
        self.action = None
        self.fields = {}
        self.inside = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "form" and attrs.get("id") == "kc-form-login":
            self.action = attrs["action"]
            self.inside = True
        if tag == "input" and self.inside and attrs.get("name"):
            self.fields[attrs["name"]] = attrs.get("value", "")

    def handle_endtag(self, tag):
        if tag == "form":
            self.inside = False


class ErrorText(HTMLParser):
    """Read visible error text without form values, links, scripts or tokens."""
    def __init__(self):
        super().__init__()
        self.skip = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.skip += 1

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.skip = max(0, self.skip - 1)

    def handle_data(self, data):
        if not self.skip and data.strip():
            self.parts.append(data.strip())


def login_error(error, jar):
    body = error.read(32768).decode(errors="replace")
    try:
        parsed = json.loads(body)
        text = " | ".join(str(parsed[key]) for key in ("error", "error_description", "detail") if key in parsed)
    except (ValueError, TypeError):
        visible = ErrorText()
        visible.feed(body)
        text = " ".join(visible.parts)
    # Never include URL queries, request bodies, cookie values or raw response HTML.
    return json.dumps({"stage": "login_failed", "http_status": error.code,
                       "response_path": urlparse(error.url).path,
                       "message": text[:1200],
                       "cookie_metadata": [{"name": cookie.name, "secure": cookie.secure,
                                            "path": cookie.path} for cookie in jar]})


def browser_login(email, password=PASSWORD):
    jar = http.cookiejar.CookieJar(policy=LocalhostBrowserCookiePolicy())
    client = build_opener(GatewayHTTPHandler(), HTTPCookieProcessor(jar))
    with client.open(ORIGIN + "/api/oidc/login?returnTo=/notifications", timeout=30) as response:
        form = LoginForm()
        form.feed(response.read().decode())
    if not form.action:
        raise RuntimeError("Keycloak login form missing; inspect realm import and gateway logs")
    form.fields.update(username=email, password=password)
    request = Request(form.action, data=urlencode(form.fields).encode(), headers={
        "Content-Type": "application/x-www-form-urlencoded", "Origin": ORIGIN,
    })
    try:
        with client.open(request, timeout=30) as response:
            page = response.read().decode()
            if urlparse(response.url).path != "/notifications":
                raise RuntimeError("Keycloak sign-in did not finish at the notification page")
            assert "Notifications" in page
    except HTTPError as error:
        raise RuntimeError(login_error(error, jar)) from None
    if not any(cookie.name == "notifications_token" for cookie in jar):
        raise RuntimeError("OIDC callback did not set the access-token cookie")
    return client


def request(client, path, body=None, token=None):
    headers = {"Origin": ORIGIN}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode()
    with client.open(Request(ORIGIN + path, data=data, headers=headers), timeout=30) as response:
        return json.load(response)


def main():
    customer = browser_login("nong@example.com")
    provider = browser_login("sparkle@example.com")
    other_provider = browser_login("fixit@example.com")
    service = request(customer, "/api/services/2")
    addresses = request(customer, "/api/customer/addresses")
    for offset in random.sample(range(30, 180), 10):
        day = (date.today() + timedelta(days=offset)).isoformat()
        slots = request(customer, f"/api/providers/1/slots?date={day}&duration={service['duration_min']}")["slots"]
        if slots:
            break
    else:
        raise RuntimeError("No seeded provider slot is available for the integration booking")
    booked = request(customer, "/api/bookings", {
        "provider_id": 1, "address_id": addresses[0]["id"], "service_date": day,
        "starting_time": slots[0], "items": [{"service_id": 2, "quantity": 1}], "payment_method": "cod",
    })
    order_id = booked["order"]["id"]
    deadline = time.monotonic() + 60
    while True:
        inbox = request(provider, "/api/notifications")
        found = next((row for row in inbox if row["order_id"] == order_id), None)
        if found:
            break
        if time.monotonic() > deadline:
            raise RuntimeError("Booking notification did not reach the authenticated inbox")
        time.sleep(1)
    with provider.open(ORIGIN + "/notifications", timeout=30) as response:
        assert found["title"] in response.read().decode(), "Server-rendered inbox did not use remote data"
    marked = request(provider, f"/api/notifications/{found['id']}/read", {})
    assert marked["read_at"] is not None
    try:
        request(other_provider, f"/api/notifications/{found['id']}/read", {})
    except HTTPError as error:
        assert error.code == 403, f"Expected ownership rejection 403, got {error.code}"
    else:
        raise AssertionError("Another provider was allowed to mark the notification read")
    try:
        request(provider, "/api/notifications", token="forged.invalid.token")
    except HTTPError as error:
        assert error.code == 401, f"Expected forged token rejection 401, got {error.code}"
    else:
        raise AssertionError("Forged bearer token was accepted")
    print(json.dumps({"result": "PASS", "flow": "Keycloak code+PKCE -> nginx -> remote inbox -> mark read",
                      "order_id": order_id, "notification_id": found["id"],
                      "ownership_rejection": 403, "forged_token_rejection": 401}))


if __name__ == "__main__":
    main()
