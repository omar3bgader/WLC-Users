import os
import urllib3
import requests
from dotenv import load_dotenv
from flask import Flask, request, jsonify, render_template
from requests.auth import HTTPBasicAuth

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
load_dotenv()

app = Flask(__name__)

# WLC config
WLC_IP    = os.getenv("WLC_IP")
WLC_USER  = os.getenv("WLC_USER")
WLC_PASS  = os.getenv("WLC_PASS")
RESTCONF  = f"https://{WLC_IP}/restconf/data/"
HEADERS   = {
    "Accept":       "application/yang-data+json",
    "Content-Type": "application/yang-data+json"
}

# DNA Center config
DNA_IP    = os.getenv("DNA_IP")
DNA_USER  = os.getenv("DNA_USER")
DNA_PASS  = os.getenv("DNA_PASS")
DNAC_V1   = f"https://{DNA_IP}/dna/intent/api/v1"
DNAC_V2   = f"https://{DNA_IP}/dna/intent/api/v2"

# Floor code mapping
CODE_MAP = {
    "Basement":"B","Ground":"F0","First":"F1","Second":"F2",
    "Third":"F3","Fourth":"F4","Fifth":"F5","Sixth":"F6","Seventh":"F7"
}

def fetch_clients():
    resp = requests.get(
        RESTCONF + "Cisco-IOS-XE-wireless-client-oper:client-oper-data",
        auth=HTTPBasicAuth(WLC_USER, WLC_PASS),
        headers=HEADERS,
        verify=False,
        timeout=10
    )
    resp.raise_for_status()
    return resp.json().get("Cisco-IOS-XE-wireless-client-oper:client-oper-data", {}).get("common-oper-data", [])

def fetch_ap_name_mac_map():
    resp = requests.get(
        RESTCONF + "Cisco-IOS-XE-wireless-access-point-oper:access-point-oper-data/ap-name-mac-map",
        auth=HTTPBasicAuth(WLC_USER, WLC_PASS),
        headers=HEADERS,
        verify=False,
        timeout=10
    )
    resp.raise_for_status()
    data = resp.json().get("Cisco-IOS-XE-wireless-access-point-oper:ap-name-mac-map", [])
    return {
        item["wtp-name"]: item["wtp-mac"].lower().replace(":", "")
        for item in data
        if "wtp-name" in item and "wtp-mac" in item
    }

def get_dnac_token():
    resp = requests.post(
        f"https://{DNA_IP}/dna/system/api/v1/auth/token",
        auth=HTTPBasicAuth(DNA_USER, DNA_PASS),
        verify=False,
        timeout=10
    )
    resp.raise_for_status()
    return resp.json().get("Token")

def fetch_floor_meta(floor_id):
    token = get_dnac_token()
    resp = requests.get(
        f"{DNAC_V2}/floors/{floor_id}",
        headers={"X-Auth-Token": token, "Accept": "application/json"},
        verify=False,
        timeout=10
    )
    resp.raise_for_status()
    return resp.json().get("response", {})

def fetch_planned_aps(floor_id):
    token = get_dnac_token()
    resp = requests.get(
        f"{DNAC_V1}/floors/{floor_id}/planned-access-points",
        headers={"X-Auth-Token": token, "Accept": "application/json"},
        verify=False,
        timeout=10
    )
    resp.raise_for_status()
    return resp.json().get("response", [])

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/api/clients')
def api_clients():
    try:
        out = []
        for c in fetch_clients():
            ap = c.get("ap-name", "") or ""
            parts = ap.split("-")
            floor = parts[0] if len(parts) == 3 else None
            side = ("Left" if parts[2].upper() == "L" else "Right") if len(parts) == 3 else None
            out.append({
                "username": c.get("username"),
                "device_hostname": c.get("device-hostname"),
                "mac_address": c.get("client-mac"),
                "ap_name": ap,
                "floor": floor,
                "side": side
            })
        return jsonify(out)
    except Exception as e:
        return jsonify(error=str(e)), 500

@app.route('/api/locate-user')
def api_locate_user():
    u = request.args.get("username", "").strip().lower()
    if not u:
        return jsonify(error="Username is required"), 400
    try:
        clients = fetch_clients()
        m = next((c for c in clients if (c.get("username") or "").lower() == u), None)
        if not m:
            return jsonify(error="User not found"), 404
        ap = m.get("ap-name", "") or ""
        parts = ap.split("-")
        floor = parts[0] if len(parts) == 3 else None
        side = ("Left" if parts[2].upper() == "L" else "Right") if len(parts) == 3 else None
        return jsonify({
            "username": m.get("username"),
            "device_hostname": m.get("device-hostname"),
            "mac_address": m.get("client-mac"),
            "ap_name": ap,
            "location": {"floor": floor, "side": side}
        })
    except Exception as e:
        return jsonify(error=str(e)), 500

@app.route('/api/floors')
def api_floors():
    floors = [
        {"id": "8709152a-cc84-4839-b947-63543a3545d8", "code": "B",  "label": "Basement"},
        {"id": "42ead930-a0ca-4d9b-a1e1-6fa1019f67e1", "code": "F0", "label": "Ground"},
        {"id": "18251519-6898-41e2-9159-9cdb24f845d6", "code": "F1", "label": "First"},
        {"id": "ace3b88c-68ef-4629-85c2-51dc5ffc53d0", "code": "F2", "label": "Second"},
        {"id": "a130fab3-3577-4de1-af82-0352a37b001d", "code": "F3", "label": "Third"},
        {"id": "63a97e04-aa9d-4701-bdeb-a953d2dd5455", "code": "F4", "label": "Fourth"},
        {"id": "0dffebdc-d3ac-4d30-919d-b61752c0436b", "code": "F5", "label": "Fifth"},
        {"id": "d588422d-fb24-43a0-9872-5256e06ab7af", "code": "F6", "label": "Sixth"},
        {"id": "a1866ff5-d0ee-4f94-a0d1-7b3936447090", "code": "F7", "label": "Seventh"},
    ]
    return jsonify(floors)

@app.route('/api/floor-map')
def api_floor_map():
    floor_id = request.args.get("floor")
    target_ap_label = request.args.get("target_ap", "").strip()

    if not floor_id:
        return jsonify(error="Floor is required"), 400

    try:
        meta = fetch_floor_meta(floor_id)
        dims = {"width": float(meta.get("width", 0)), "length": float(meta.get("length", 0))}
        name = meta.get("name", "")
        parts = name.split("-", 1)
        suffix = parts[1].strip() if len(parts) == 2 else None
        code = CODE_MAP.get(suffix)
        if not code:
            return jsonify(error=f"No map for floor {name}"), 404
        image_url = f"/static/maps/{code}.png"

        planned_aps = fetch_planned_aps(floor_id)
        ap_mac_map = fetch_ap_name_mac_map()
        target_mac = ap_mac_map.get(target_ap_label, "").lower().replace(":", "")

        for ap in planned_aps:
            mac = ap["attributes"].get("macaddress", "").lower().replace(":", "")
            name = ap["attributes"].get("name")

        target_ap_dna_name = next(
            (ap["attributes"]["name"] for ap in planned_aps
             if ap["attributes"].get("macaddress", "").lower().replace(":", "") == target_mac),
            None
        )

        aps = []
        for ap in planned_aps:
            a = ap["attributes"]
            p = ap["position"]
            aps.append({
                "name": a.get("name"),
                "x": p.get("x"),
                "y": p.get("y"),
                "is_target": a.get("name") == target_ap_dna_name
            })

        return jsonify({"dimensions": dims, "aps": aps, "image_url": image_url})

    except Exception as e:
        return jsonify(error=str(e)), 500

if __name__ == "__main__":
    from waitress import serve
    serve(app, host="0.0.0.0", port=5000)