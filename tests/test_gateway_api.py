import sys, types, importlib.util, pathlib, json, asyncio
PKG = pathlib.Path(__file__).resolve().parents[1] / "custom_components" / "milesight_lorawan"
for n in ("mlw", "mlw.lns"):
    m = types.ModuleType(n); m.__path__ = [str(PKG / ("lns" if n.endswith("lns") else ""))]; sys.modules[n] = m
def L(n, pkg="mlw"):
    s = importlib.util.spec_from_file_location(f"{pkg}.{n}", (PKG / "lns" / "crypto.py") if n == "crypto" else (PKG / (n + ".py")))
    mod = importlib.util.module_from_spec(s); sys.modules[f"{pkg}.{n}"] = mod; s.loader.exec_module(mod); return mod
L("crypto", "mlw.lns")
# stub aiohttp
aiohttp = types.ModuleType("aiohttp"); aiohttp.ClientTimeout = lambda total=None: None
sys.modules["aiohttp"] = aiohttp
ga = L("gateway_api")
fix = json.load(open(pathlib.Path(__file__).resolve().parent / "gateway_fixtures.json"))

class Resp:
    def __init__(self, obj): self._obj = obj; self.status = 200
    async def text(self): return json.dumps(self._obj)
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False

class Session:
    def __init__(self): self.requests = []
    def request(self, method, url, data=None, headers=None, timeout=None):
        self.requests.append({"method": method, "url": url, "data": data, "headers": headers})
        if url.endswith("/api/internal/login"): return Resp({"jwt": "JWT123"})
        if url.endswith("/cgi"):
            body = json.loads(data)
            if body["core"] == "user" and body["function"] == "login":
                # the router web login: needs the encrypted password, issues the td session
                assert body["values"][0]["base"] == "web_login"
                return Resp({"status": 0, "result": [{"username": "admin", "td": "TESTTD", "ysrole": 4}]})
            # every other /cgi call must carry the td session cookie
            assert headers.get("Cookie") == "loginname=admin; td=TESTTD", headers
            if body["core"] == "yruo_status": return Resp(fix["summary_response"])
            if body["core"] == "yruo_loragw" and body["function"] == "get": return Resp(fix["general_conf_response"])
            if body["core"] == "yruo_loragw" and body["function"] == "set":
                self.last_set = body; return Resp({"status": 0, "result": [{}]})
        return Resp({})

async def main():
    s = Session()
    c = ga.GatewayClient(s, "192.168.1.230", "admin", "pw")
    await c.login()
    # login does the router web login (/cgi user.login) first: form body, encrypted password, no auth header
    wl = s.requests[0]
    assert wl["url"].endswith("/cgi") and wl["headers"]["Content-Type"].startswith("application/x-www-form-urlencoded")
    wlb = json.loads(wl["data"])
    assert wlb["core"] == "user" and wlb["function"] == "login"
    assert ga.decrypt_password(wlb["values"][0]["password"]) == "pw"
    assert "Authorization" not in wl["headers"], wl["headers"]
    # it captured the td session and the network-server JWT
    assert c.cgi_cookie == "loginname=admin; td=TESTTD", c.cgi_cookie
    assert c.jwt == "JWT123"
    info = await c.async_read_info()
    # /cgi carries the td cookie, not an Authorization header
    cgi = [r for r in s.requests if r["url"].endswith("/cgi")][-1]
    assert "Authorization" not in cgi["headers"] and cgi["headers"]["Cookie"] == "loginname=admin; td=TESTTD"
    assert info["model"] == "UG56-L04EU-868M" and info["eui"] == "24E124FFFEF61E38", info
    # point at HA: reads general_conf (1 semtech added) and writes it back, keeping the embedded dest
    changed = await c.async_point_at_home_assistant("192.168.1.20")
    assert changed is True
    servs = s.last_set["values"][0]["value"]["servs"]
    assert [x["serv_type"] for x in servs] == ["ursalink", "semtech"]
    assert servs[1]["serv_addr"] == "192.168.1.20" and servs[1]["serv_port_up"] == 1700
    # a network-server REST call uses the Bearer JWT instead of Basic
    s.requests.clear()
    await c.async_profiles()
    api = [r for r in s.requests if "/urprofiles" in r["url"]][0]
    assert api["headers"]["Authorization"] == "Bearer JWT123", api["headers"]
    print("transport ok:", info["model"], "| no-auth login+cgi | api=Bearer")

async def basic_fallback():
    # older firmware that rejects /cgi with no header but accepts HTTP Basic auth
    import base64
    basic = "Basic " + base64.b64encode(b"admin:pw").decode()
    class FallbackSession:
        def __init__(self): self.requests = []
        def request(self, method, url, data=None, headers=None, timeout=None):
            self.requests.append({"url": url, "headers": headers, "data": data})
            if url.endswith("/api/internal/login"): return Resp({"jwt": "JWT123"})
            if url.endswith("/cgi"):
                body = json.loads(data)
                if body["core"] == "user" and body["function"] == "login":   # no web_login on this old firmware
                    return Resp({"status": -2, "result": [-32001, "Session not found"]})
                if headers.get("Authorization", "") != basic:        # no-header attempt is refused
                    return Resp({"status": -2, "result": [-32001, "Session not found"]})
                if body["core"] == "yruo_status": return Resp(fix["summary_response"])
                if body["core"] == "yruo_loragw": return Resp(fix["general_conf_response"])
            return Resp({})
    s = FallbackSession()
    c = ga.GatewayClient(s, "192.168.1.230", "admin", "pw")
    await c.login()
    info = await c.async_read_info()
    assert info["model"] == "UG56-L04EU-868M", info
    # the yruo_status read tried no-header first, then fell back to Basic
    status_cgis = [r for r in s.requests if r["url"].endswith("/cgi") and "yruo_status" in (r["data"] or "")]
    assert "Authorization" not in status_cgis[0]["headers"]
    assert status_cgis[1]["headers"]["Authorization"] == basic
    print("basic fallback ok: /cgi recovered via Basic when no-header was refused")

async def reason_surfaced():
    # when the gateway refuses under every scheme, the error carries its actual reply
    class DenySession:
        def request(self, method, url, data=None, headers=None, timeout=None):
            if url.endswith("/api/internal/login"): return Resp({"jwt": "JWT123"})
            return Resp({"status": 1, "msg": "permission denied"})
    c = ga.GatewayClient(DenySession(), "192.168.1.230", "admin", "pw")
    await c.login()
    try:
        await c.async_read_info()
    except ga.GatewayError as err:
        assert "status=1" in str(err) and "permission denied" in str(err), err
        print("reason surfaced ok:", err)
        return
    raise AssertionError("expected GatewayError")

asyncio.run(main())
asyncio.run(basic_fallback())
asyncio.run(reason_surfaced())
