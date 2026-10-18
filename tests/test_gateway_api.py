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
    hdr = s.requests[-1]["headers"]
    assert hdr["Authorization"] == "Bearer JWT123" and hdr["Cookie"] == "token=JWT123"
    assert info["model"] == "UG56-L04EU-868M" and info["eui"] == "24E124FFFEF61E38", info
    # point at HA: reads general_conf (1 semtech added) and writes it back, keeping the embedded dest
    changed = await c.async_point_at_home_assistant("192.168.1.20")
    assert changed is True
    servs = s.last_set["values"][0]["value"]["servs"]
    assert [x["serv_type"] for x in servs] == ["ursalink", "semtech"]
    assert servs[1]["serv_addr"] == "192.168.1.20" and servs[1]["serv_port_up"] == 1700
    print("transport ok:", info["model"], "| semtech added")
asyncio.run(main())
