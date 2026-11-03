"""Weather from Open-Meteo: free, no API key."""
import httpx

from .. import config
from .base import Tool, ToolContext, ToolError

TRANSPORT = None  # tests inject an httpx.MockTransport here

WMO = {0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast", 45: "fog", 48: "freezing fog",
       51: "light drizzle", 53: "drizzle", 55: "heavy drizzle", 56: "freezing drizzle", 57: "freezing drizzle",
       61: "light rain", 63: "rain", 65: "heavy rain", 66: "freezing rain", 67: "freezing rain",
       71: "light snow", 73: "snow", 75: "heavy snow", 77: "snow grains", 80: "rain showers", 81: "rain showers",
       82: "violent rain showers", 85: "snow showers", 86: "heavy snow showers", 95: "thunderstorm",
       96: "thunderstorm with hail", 99: "thunderstorm with heavy hail"}


class GetWeather(Tool):
    name = "get_weather"
    description = ("Current weather and a 3-day forecast for a city (default: the user's home city). Pass the city name "
                   "in English, e.g. 'Tashkent', 'Samarkand', 'Moscow'. Returns temperatures in °C.")
    input_schema = {"type": "object", "properties": {"city": {"type": "string"}}}
    side_effect = False

    async def run(self, args, ctx: ToolContext):
        city = str(args.get("city") or config.HOME_CITY).strip()
        async with httpx.AsyncClient(timeout=15, transport=TRANSPORT) as c:
            try:
                g = (await c.get("https://geocoding-api.open-meteo.com/v1/search",
                                 params={"name": city, "count": 1, "format": "json"})).json()
                place = (g.get("results") or [None])[0]
                if not place:
                    raise ToolError(f"city '{city}' not found; try its English name")
                f = (await c.get("https://api.open-meteo.com/v1/forecast", params={
                    "latitude": place["latitude"], "longitude": place["longitude"], "timezone": "auto", "forecast_days": 3,
                    "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m",
                    "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max"})).json()
            except httpx.HTTPError as e:
                raise ToolError(f"weather service unreachable: {type(e).__name__}")
        cur, d = f.get("current", {}), f.get("daily", {})
        days = [{"date": d["time"][i], "max": d["temperature_2m_max"][i], "min": d["temperature_2m_min"][i],
                 "rain_chance": (d.get("precipitation_probability_max") or [None] * 3)[i],
                 "sky": WMO.get(d["weather_code"][i], "unknown")} for i in range(len(d.get("time", [])))]
        return {"place": f"{place['name']}, {place.get('country', '')}".strip(", "),
                "now": {"temp": cur.get("temperature_2m"), "feels_like": cur.get("apparent_temperature"),
                        "humidity": cur.get("relative_humidity_2m"), "wind_kmh": cur.get("wind_speed_10m"),
                        "sky": WMO.get(cur.get("weather_code"), "unknown")},
                "days": days}
