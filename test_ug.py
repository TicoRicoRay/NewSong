"""Debug - check if auth token changes tab/info response"""
from ug_fetch import generate_device_id, login, make_headers, api_get
from config import UG_EMAIL, UG_PASSWORD

device_id = generate_device_id()
token = login(device_id, UG_EMAIL, UG_PASSWORD)

# Try community tab WITHOUT token (as anonymous)
print("=== Community tab WITHOUT token ===")
headers_anon = make_headers(device_id, token=None)
result = api_get("/tab/info", {"tab_id": 15114, "tab_access_type": "private"}, headers_anon)
if result:
    tv = result.get("tab_view", {}) or {}
    wiki = tv.get("wiki_tab", {}) or {}
    content = wiki.get("content", "") or ""
    print("content length:", len(content))
    print("tab_view keys:", list(tv.keys()))
    print("preview:", content[:200] if content else "EMPTY")
else:
    print("No result")

# Try community tab WITH token
print("\n=== Community tab WITH token ===")
headers_auth = make_headers(device_id, token)
result2 = api_get("/tab/info", {"tab_id": 15114, "tab_access_type": "private"}, headers_auth)
if result2:
    tv = result2.get("tab_view", {}) or {}
    wiki = tv.get("wiki_tab", {}) or {}
    content = wiki.get("content", "") or ""
    print("content length:", len(content))
    print("tab_view keys:", list(tv.keys()))
    print("preview:", content[:200] if content else "EMPTY")
else:
    print("No result")

# Print full raw response for community tab (truncated)
print("\n=== Full raw response keys (community, with token) ===")
if result2:
    for k, v in result2.items():
        vstr = str(v)
        if v is not None and v != [] and v != {}:
            print(f"  {k}: {vstr[:100]}")
