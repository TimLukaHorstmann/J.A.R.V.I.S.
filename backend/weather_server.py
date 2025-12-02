from mcp.server.fastmcp import FastMCP
import httpx

mcp = FastMCP("weather")

@mcp.tool()
async def get_weather(city: str) -> str:
    """Get the current weather for a given city."""
    async with httpx.AsyncClient() as client:
        # 1. Geocoding
        geo_url = "https://geocoding-api.open-meteo.com/v1/search"
        geo_resp = await client.get(geo_url, params={"name": city, "count": 1, "language": "en", "format": "json"})
        geo_data = geo_resp.json()
        
        if not geo_data.get("results"):
            return f"Could not find location: {city}"
            
        location = geo_data["results"][0]
        lat = location["latitude"]
        lon = location["longitude"]
        name = location["name"]
        country = location.get("country", "")
        
        # 2. Weather
        weather_url = "https://api.open-meteo.com/v1/forecast"
        params = {
            "latitude": lat,
            "longitude": lon,
            "current": ["temperature_2m", "relative_humidity_2m", "apparent_temperature", "precipitation", "weather_code", "wind_speed_10m"],
            "daily": ["weather_code", "temperature_2m_max", "temperature_2m_min"],
            "timezone": "auto"
        }
        
        weather_resp = await client.get(weather_url, params=params)
        weather_data = weather_resp.json()
        
        if "current" not in weather_data:
            return "Could not retrieve weather data."
            
        current = weather_data["current"]
        daily = weather_data.get("daily", {})
        
        # WMO Weather interpretation codes (simplified)
        wmo_codes = {
            0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
            45: "Fog", 48: "Depositing rime fog",
            51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
            61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
            71: "Slight snow", 73: "Moderate snow", 75: "Heavy snow",
            95: "Thunderstorm", 96: "Thunderstorm with slight hail", 99: "Thunderstorm with heavy hail"
        }
        
        weather_desc = wmo_codes.get(current["weather_code"], "Unknown")
        
        report = f"Weather in {name}, {country}:\n"
        report += f"Condition: {weather_desc}\n"
        report += f"Temperature: {current['temperature_2m']}°C (Feels like {current['apparent_temperature']}°C)\n"
        report += f"Humidity: {current['relative_humidity_2m']}%\n"
        report += f"Wind Speed: {current['wind_speed_10m']} km/h\n"
        
        if daily and "temperature_2m_max" in daily:
             report += f"Forecast: High: {daily['temperature_2m_max'][0]}°C, Low: {daily['temperature_2m_min'][0]}°C\n"
             
        return report

if __name__ == "__main__":
    # Run in stdio mode (default) so supergateway can wrap it
    mcp.run()
