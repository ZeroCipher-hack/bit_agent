"""Smart home through Home Assistant (REST API). Works with anything HA knows: AC, lights, plugs, TV, smart fridges...
Locks, alarms and garage doors/covers always need the user's yes."""
import json

import httpx

from .. import config
from .base import Tool, ToolContext, ToolError

TRANSPORT = None  # tests inject an httpx.MockTransport
RISKY_DOMAINS = {"lock", "alarm_control_panel", "cover"}
ALLOWED_DOMAINS = {"light", "switch", "fan", "climate", "media_player", "scene", "script", "number", "water_heater",
                   "humidifier", "vacuum", "input_boolean"} | RISKY_DOMAINS

ACTIONS = ["turn_on", "turn_off", "toggle", "set_temperature", "set_mode", "open", "close", "lock", "unlock"]


def _ready():
    if not (config.HA_URL and config.HA_TOKEN):
        raise ToolError("smart home is not connected (set HA_URL and HA_TOKEN in .env)")


def _aliases() -> dict:
    try:
        return {k.strip().lower(): v for k, v in json.loads(config.DEVICES_FILE.read_text(encoding="utf-8")).items()}
    except (OSError, ValueError):
        return {}


async def _ha(method: str, path: str, body: dict | None = None):
    _ready()
    async with httpx.AsyncClient(timeout=15, transport=TRANSPORT) as c:
        try:
            r = await c.request(method, f"{config.HA_URL}{path}", json=body,
                                headers={"Authorization": f"Bearer {config.HA_TOKEN}"})
        except httpx.HTTPError as e:
            raise ToolError(f"Home Assistant unreachable: {type(e).__name__}")
    if r.status_code == 401:
        raise ToolError("Home Assistant rejected the token")
    if r.status_code >= 400:
        raise ToolError(f"Home Assistant error {r.status_code}: {r.text[:200]}")
    return r.json() if r.content else {}


async def _states():
    return [s for s in await _ha("GET", "/api/states") if s["entity_id"].split(".")[0] in ALLOWED_DOMAINS]


async def resolve(name: str) -> dict:
    key = name.strip().lower()
    states = await _states()
    target = _aliases().get(key, key)
    for s in states:
        if s["entity_id"] == target:
            return s
    hits = [s for s in states if key in str(s.get("attributes", {}).get("friendly_name", "")).lower()]
    if len(hits) == 1:
        return hits[0]
    if not hits:
        raise ToolError(f"no device matches '{name}'. Call home_devices to see names, or add an alias in data/devices.json")
    names = ", ".join(str(h["attributes"].get("friendly_name", h["entity_id"])) for h in hits[:8])
    raise ToolError(f"'{name}' matches several devices: {names}. Ask the user which one")


def _domain(entity_id: str) -> str:
    return entity_id.split(".")[0]


def plan(entity_id: str, action: str, value=None) -> tuple[str, str, dict]:
    """(domain, service, data) for an action on an entity."""
    d, data = _domain(entity_id), {"entity_id": entity_id}
    if action in ("turn_on", "turn_off", "toggle"):
        if d in ("scene", "script") and action != "turn_on":
            raise ToolError(f"{d} can only be turned on")
        return d, action, data
    if action == "set_temperature":
        if value is None:
            raise ToolError("value (temperature) is required")
        if d == "climate" or d == "water_heater":
            return d, "set_temperature", {**data, "temperature": float(value)}
        if d == "number":
            return d, "set_value", {**data, "value": float(value)}
        raise ToolError(f"{entity_id} has no temperature")
    if action == "set_mode":
        if d == "climate":
            return d, "set_hvac_mode", {**data, "hvac_mode": str(value)}
        if d == "fan":
            return d, "set_preset_mode", {**data, "preset_mode": str(value)}
        raise ToolError(f"{entity_id} has no modes")
    if action in ("open", "close") and d == "cover":
        return d, f"{action}_cover", data
    if action in ("lock", "unlock") and d == "lock":
        return d, action, data
    raise ToolError(f"action {action} is not possible for {entity_id}")


class HomeDevices(Tool):
    name = "home_devices"
    description = "List smart-home devices (Home Assistant) with their names and current state. Returns a list."
    side_effect = False

    async def run(self, args, ctx: ToolContext):
        out = [{"id": s["entity_id"], "name": s.get("attributes", {}).get("friendly_name", s["entity_id"]), "state": s["state"]}
               for s in await _states()]
        return out[:80]


class HomeStatus(Tool):
    name = "home_status"
    description = "Read one smart-home device's state (on/off, temperature, mode...). device = its name or alias. Returns the state."
    input_schema = {"type": "object", "properties": {"device": {"type": "string"}}, "required": ["device"]}
    side_effect = False

    async def run(self, args, ctx: ToolContext):
        s = await resolve(str(args.get("device", "")))
        attrs = s.get("attributes", {})
        keep = ("friendly_name", "temperature", "current_temperature", "hvac_mode", "hvac_modes", "brightness",
                "unit_of_measurement", "preset_mode", "volume_level")
        return {"id": s["entity_id"], "state": s["state"], **{k: attrs[k] for k in keep if k in attrs}}


class HomeControl(Tool):
    name = "home_control"
    description = ("Control a smart-home device through Home Assistant: turn on/off the AC, lights, TV, plugs; set the AC "
                   "or fridge temperature; change modes. device = the name the user uses. Locks, alarms and garage "
                   "doors ask the user first. Returns {ok, device}.")
    input_schema = {"type": "object", "properties": {
        "device": {"type": "string"}, "action": {"type": "string", "enum": ACTIONS},
        "value": {"description": "temperature for set_temperature, mode for set_mode"}}, "required": ["device", "action"]}

    def validate(self, args):
        _ready()
        if args.get("action") not in ACTIONS:
            raise ToolError(f"action must be one of {ACTIONS}")

    def is_risky(self, args) -> bool:
        target = _aliases().get(str(args.get("device", "")).strip().lower(), str(args.get("device", "")))
        word = str(args.get("device", "")).lower()
        return (_domain(target) in RISKY_DOMAINS or args.get("action") in ("open", "close", "lock", "unlock")
                or any(w in word for w in ("qulf", "eshik", "darvoza", "garaj", "signal", "замок", "дверь", "lock", "door", "garage", "alarm")))

    def summary(self, args):
        v = f" = {args['value']}" if args.get("value") is not None else ""
        return f"Uy: {args['device']} → {args['action']}{v}"

    async def run(self, args, ctx: ToolContext):
        s = await resolve(str(args["device"]))
        domain, service, data = plan(s["entity_id"], args["action"], args.get("value"))
        if domain in RISKY_DOMAINS and not ctx.confirmed:
            raise ToolError("this device needs the user's confirmation")
        await _ha("POST", f"/api/services/{domain}/{service}", data)
        return {"ok": True, "device": s.get("attributes", {}).get("friendly_name", s["entity_id"]), "service": f"{domain}.{service}"}
