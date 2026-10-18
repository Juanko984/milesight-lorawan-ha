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
            if body["core"] == "yruo_status": return Resp(fix["summary_response"])
            if body["core"] == "yruo_loragw" and body["function"] == "get": return Resp(fix["general_conf_response"])
            if body["core"] == "yruo_loragw" and body["function"] == "set":
                self.last_set = body; return Resp({"status": 0, "result": [{}]})
        return Resp({})

async def main():
    s = Session()
    c = ga.GatewayClient(s, "192.168.1.230", "admin", "pw")
    await c.login()
    # the login must send a form-urlencoded JSON string body, and the password encrypted
    lr = s.requests[0]
    assert lr["headers"]["Content-Type"].startswith("application/x-www-form-urlencoded"), lr["headers"]
    sent = json.loads(lr["data"]); assert sent["username"] == "admin" and ga.decrypt_password(sent["password"]) == "pw"
    assert c.jwt == "JWT123"
    # after login the JWT rides as Bearer AND cookie
    info = await c.async_read_info()
    import base64
    basic = "Basic " + base64.b64encode(b"admin:pw").decode()
    # /cgi is authorised by HTTP Basic auth (what the gateway's whole origin uses)
    cgi = [r for r in s.requests if r["url"].endswith("/cgi")][-1]
    assert cgi["headers"]["Authorization"] == basic, cgi["headers"]
    # the login itself also uses Basic auth, not a token
    login = [r for r in s.requests if r["url"].endswith("/internal/login")][0]
    assert login["headers"]["Authorization"] == basic
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
    print("transport ok:", info["model"], "| semtech added | cgi=Basic api=Bearer")

async def bearer_fallback():
    # firmware that rejects /cgi under Basic auth but accepts it with the login JWT (Bearer)
    class FallbackSession:
        def __init__(self): self.requests = []
        def request(self, method, url, data=None, headers=None, timeout=None):
            self.requests.append({"url": url, "headers": headers})
            if url.endswith("/api/internal/login"): return Resp({"jwt": "JWT123"})
            if url.endswith("/cgi"):
                auth = headers.get("Authorization", "")
                if auth.startswith("Basic"):
                    return Resp({"status": 1, "msg": "permission denied"})
                body = json.loads(data)
                if body["core"] == "yruo_status": return Resp(fix["summary_response"])
                if body["core"] == "yruo_loragw": return Resp(fix["general_conf_response"])
            return Resp({})
    s = FallbackSession()
    c = ga.GatewayClient(s, "192.168.1.230", "admin", "pw")
    await c.login()
    info = await c.async_read_info()
    assert info["model"] == "UG56-L04EU-868M", info
    cgis = [r for r in s.requests if r["url"].endswith("/cgi")]
    assert cgis[0]["headers"]["Authorization"].startswith("Basic")   # tried Basic first
    assert cgis[1]["headers"]["Authorization"] == "Bearer JWT123"    # fell back to Bearer
    print("bearer fallback ok: /cgi recovered via JWT when Basic was refused")

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
asyncio.run(bearer_fallback())
asyncio.run(reason_surfaced())
