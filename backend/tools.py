# tools.py

import json
import math
import requests
import datetime
import time
from zoneinfo import ZoneInfo
from duckduckgo_search import DDGS
from bs4 import BeautifulSoup
import re
from forex_python.converter import CurrencyRates
from newsapi import NewsApiClient
import trafilatura

def get_current_temperature(location: str = None, coordinates: dict = None) -> float:
    """
    Get the current temperature at a location using the free Open-Meteo APIs.

    Args:
        location: e.g. "Paris, France" (optional if coordinates provided)
        coordinates: dict with "lat" and "lon" keys (optional if location provided)
    Returns:
        Temperature in Celsius.
    """
    start = time.time()
    
    # If coordinates are provided, use them directly
    if coordinates and "lat" in coordinates and "lon" in coordinates:
        lat, lon = coordinates["lat"], coordinates["lon"]
    elif location:
        # Otherwise use geocoding API to get coordinates from location name
        geo = requests.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": location, "count": 1},
            timeout=10
        )
        geo.raise_for_status()
        res = geo.json().get("results")
        if not res:
            raise ValueError(f"Location '{location}' not found.")
        lat, lon = res[0]["latitude"], res[0]["longitude"]
    else:
        raise ValueError("Either location name or coordinates must be provided.")

    weather = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={"latitude": lat, "longitude": lon, "current_weather": True},
        timeout=10
    )
    weather.raise_for_status()
    temp = weather.json().get("current_weather", {}).get("temperature")
    if temp is None:
        raise RuntimeError("No temperature in response.")
    return temp

def get_current_datetime() -> str:
    """
    Get the current local date and time of the server.

    Returns:
        Formatted string, e.g. "Sunday, April 27, 2025 at 03:14 PM".
    """
    now = datetime.datetime.now()
    return now.strftime("%A, %B %d, %Y at %I:%M %p")

def get_weather_forecast(location: str = None, date: str = None, coordinates: dict = None) -> str:
    """
    Get the weather forecast for a location on a specific date.

    Args:
        location: e.g. "Paris, France" (optional if coordinates provided)
        date: in "YYYY-MM-DD" format, defaults to tomorrow if not provided
        coordinates: dict with "lat" and "lon" keys (optional if location provided)
    Returns:
        A summary like "Forecast for Paris, France on 2025-04-28: max 18°C, min 7°C"
    """
    # Set default date to tomorrow if not provided
    if not date:
        tomorrow = datetime.datetime.now() + datetime.timedelta(days=1)
        date = tomorrow.strftime("%Y-%m-%d")
    
    # Validate date format
    try:
        datetime.datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        raise ValueError("Date must be in YYYY-MM-DD format")
    
    # If coordinates are provided, use them directly
    if coordinates and "lat" in coordinates and "lon" in coordinates:
        lat, lon = coordinates["lat"], coordinates["lon"]
        # Try to get location name for better output
        if not location:
            try:
                geo = requests.get(
                    "https://geocoding-api.open-meteo.com/v1/search",
                    params={"latitude": lat, "longitude": lon, "count": 1},
                    timeout=10
                )
                geo.raise_for_status()
                res = geo.json().get("results")
                if res:
                    location = res[0]["name"]
                else:
                    location = f"coordinates ({lat}, {lon})"
            except:
                location = f"coordinates ({lat}, {lon})"
    elif location:
        # Otherwise use geocoding API to get coordinates from location name
        geo = requests.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": location, "count": 1},
            timeout=10
        )
        geo.raise_for_status()
        res = geo.json().get("results")
        if not res:
            raise ValueError(f"Location '{location}' not found.")
        lat, lon = res[0]["latitude"], res[0]["longitude"]
    else:
        raise ValueError("Either location name or coordinates must be provided.")

    f = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": lat,
            "longitude": lon,
            "daily": ["temperature_2m_max", "temperature_2m_min", "precipitation_sum", "weathercode"],
            "start_date": date,
            "end_date": date,
            "timezone": "auto"
        },
        timeout=10
    )
    f.raise_for_status()
    daily = f.json().get("daily", {})
    max_t = daily.get("temperature_2m_max", [None])[0]
    min_t = daily.get("temperature_2m_min", [None])[0]
    precip = daily.get("precipitation_sum", [None])[0]
    weather_code = daily.get("weathercode", [None])[0]
    
    if max_t is None or min_t is None:
        raise RuntimeError("Forecast data missing.")
    
    # Map weather code to description
    weather_descriptions = {
        0: "Clear sky",
        1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
        45: "Fog", 48: "Depositing rime fog",
        51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
        56: "Light freezing drizzle", 57: "Dense freezing drizzle",
        61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
        66: "Light freezing rain", 67: "Heavy freezing rain",
        71: "Slight snow fall", 73: "Moderate snow fall", 75: "Heavy snow fall",
        77: "Snow grains",
        80: "Slight rain showers", 81: "Moderate rain showers", 82: "Violent rain showers",
        85: "Slight snow showers", 86: "Heavy snow showers",
        95: "Thunderstorm", 96: "Thunderstorm with slight hail", 99: "Thunderstorm with heavy hail"
    }
    
    weather_description = weather_descriptions.get(weather_code, "Unknown conditions")
    
    precipitation_info = f", {precip}mm precipitation" if precip is not None else ""
    
    return f"Forecast for {location} on {date}: {weather_description}, max {max_t}°C, min {min_t}°C{precipitation_info}"

def get_time_in_location(location: str) -> str:
    """
    Get the current local time at a given location.

    Args:
        location: e.g. "New York, USA"
    Returns:
        Formatted time, e.g. "Thursday, April 27, 2025 at 08:14 AM (America/New_York)"
    """
    geo = requests.get(
        "https://geocoding-api.open-meteo.com/v1/search",
        params={"name": location, "count": 1},
        timeout=10
    )
    geo.raise_for_status()
    res = geo.json().get("results")
    if not res or "timezone" not in res[0]:
        raise ValueError(f"Timezone for '{location}' not found.")
    tz_name = res[0]["timezone"]
    now = datetime.datetime.now(ZoneInfo(tz_name))
    return now.strftime(f"%A, %B %d, %Y at %I:%M %p ({tz_name})")

def search_web(query: str, num_results: int = 3) -> str:
    """
    Search the internet for a query, extract main content from top results using trafilatura,
    and return both information and sources.

    Args:
        query: the search query string, e.g. "latest AI news"
        num_results: how many results to fetch and process (default 3)

    Returns:
        A summary of extracted content with links to sources.
    """
    # Get search results from DuckDuckGo
    try:
        results = DDGS().text(query, max_results=num_results + 3)  # Get extra in case some fail
        if not results:
            return "No results found for this query."
    except Exception as e:
        return f"Error performing search: {str(e)}"
    
    content_items = []
    processed = 0
    
    for result in results:
        if processed >= num_results:
            break
            
        url = result.get("href") or result.get("url")
        title = result.get("title") or "(No title)"
        
        if not url or url.endswith(('.pdf', '.doc', '.docx', '.ppt', '.pptx', '.xls', '.xlsx')):
            continue  # Skip non-HTML content
            
        try:
            # Fetch the page using trafilatura with timeout
            downloaded = None
            try:
                downloaded = trafilatura.fetch_url(url, timeout=10)
            except Exception as e:
                print(f"Error fetching URL {url}: {str(e)}")
                continue
                
            if downloaded:
                # Extract the main content
                try:
                    extracted = trafilatura.extract(downloaded, include_comments=False, 
                                                  include_tables=False, favor_precision=True)
                    
                    # Explicitly close any resources to prevent ClosedResourceError
                    if hasattr(downloaded, 'close') and callable(downloaded.close):
                        try:
                            downloaded.close()
                        except:
                            pass

                    if extracted:
                        # Take the first 1000 characters
                        text = extracted[:1000] + "..." if len(extracted) > 1000 else extracted
                        content_items.append(f"From {title}:\n{text}\nSource: {url}\n")
                        processed += 1
                except Exception as e:
                    print(f"Error extracting content from {url}: {str(e)}")
                    # Ensure resources are cleaned up even on extraction error
                    if hasattr(downloaded, 'close') and callable(downloaded.close):
                        try:
                            downloaded.close()
                        except:
                            pass
        except Exception as e:
            print(f"General error processing result {url}: {str(e)}")
            continue  # Skip this result and try the next one
    
    if not content_items:
        return "Could not extract readable content from search results."
        
    # Compile the final response
    response = f"Here's what I found about '{query}':\n\n"
    response += "\n---\n".join(content_items)
    return response


def get_wikipedia_summary(topic: str, sentences: int = 2) -> str:
    """
    Fetch a brief summary of a Wikipedia article.

    Args:
        topic: the article title, e.g. "Python (programming language)"
        sentences: how many sentences to return
    Returns:
        The first N sentences of the article's summary.
    """
    url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{topic}"
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()
    extract = resp.json().get("extract", "")
    if not extract:
        raise ValueError(f"No Wikipedia page found for '{topic}'.")
    parts = extract.split(". ")
    snippet = ". ".join(parts[:sentences])
    if not snippet.endswith("."):
        snippet += "."
    return snippet

def currency_convert(amount: float, from_currency: str, to_currency: str) -> str:
    """
    Convert an amount from one currency to another using current exchange rates.
    
    Args:
        amount: The amount to convert
        from_currency: Source currency code (e.g., "USD", "EUR")
        to_currency: Target currency code (e.g., "JPY", "GBP")
    Returns:
        A string with the converted amount and relevant information
    """
    try:
        c = CurrencyRates()
        from_currency = from_currency.upper()
        to_currency = to_currency.upper()
        
        result = c.convert(from_currency, to_currency, amount)
        return f"{amount} {from_currency} = {result:.2f} {to_currency}"
    except Exception as e:
        return f"Error converting currency: {str(e)}"

def calculate(expression: str) -> str:
    """
    Calculate the result of a mathematical expression.
    
    Args:
        expression: A mathematical expression as string (e.g., "5 * (3 + 2)")
    Returns:
        The result of the calculation
    """
    # Safety check - only allow basic math operations
    allowed_chars = set("0123456789+-*/().^ ")
    if not all(c in allowed_chars for c in expression):
        return "Error: Expression contains invalid characters"
    
    try:
        # Replace ^ with ** for exponentiation
        expression = expression.replace('^', '**')
        
        # Use Python's eval with a restricted namespace for safety
        namespace = {"__builtins__": None}
        namespace.update({
            "sin": math.sin, "cos": math.cos, "tan": math.tan,
            "sqrt": math.sqrt, "pi": math.pi, "e": math.e,
            "abs": abs, "round": round
        })
        
        result = eval(expression, namespace)
        return f"{expression} = {result}"
    except Exception as e:
        return f"Error calculating result: {str(e)}"

def get_news_headlines(topic: str, count: int = 5) -> str:
    """
    Get recent news headlines for a specific topic using DuckDuckGo News search.
    
    Args:
        topic: The topic to search for news
        count: Number of headlines to return (default 5)
    Returns:
        A string with recent headlines and sources
    """
    try:
        from duckduckgo_search import DDGS
        
        # Use DuckDuckGo news search instead of requiring an API key
        results = DDGS().news(topic, max_results=count)
        
        if not results:
            return f"No recent news found for '{topic}'."
            
        result = f"Top {len(results)} headlines for '{topic}':\n\n"
        
        for i, article in enumerate(results, 1):
            title = article.get('title', 'No title')
            source = article.get('source', 'Unknown source')
            url = article.get('url', '')
            published = article.get('published', '')
            result += f"{i}. {title} ({source})\n   Published: {published}\n   {url}\n\n"
            
        return result
    except Exception as e:
        return f"Error fetching news: {str(e)}"

def translate_text(text: str, target_language: str) -> str:
    """
    Translate text to the target language.
    
    Args:
        text: Text to translate
        target_language: Language code to translate to (e.g., "es", "fr", "de")
    Returns:
        The translated text
    """
    try:
        # Using LibreTranslate API (open source)
        url = "https://libretranslate.com/translate"
        
        payload = {
            "q": text,
            "source": "auto",
            "target": target_language,
            "format": "text"
        }
        
        headers = {"Content-Type": "application/json"}
        
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        response.raise_for_status()
        
        result = response.json()
        if "translatedText" in result:
            return result["translatedText"]
        else:
            return f"Translation error: {result.get('error', 'Unknown error')}"
    except Exception as e:
        return f"Error translating text: {str(e)}"
