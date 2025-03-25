import requests
import os
import logging
from dotenv import load_dotenv
from flask import Flask, request, jsonify
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import redis
import json 

BASE_URL = 'https://weather.visualcrossing.com/VisualCrossingWebServices/rest/services/timeline/'
TTL = 43200

load_dotenv()
api_key = os.getenv('API_KEY')
redis_url = os.getenv('REDIS_URL')
redis_client = redis.from_url(redis_url)

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
limiter = Limiter(
    get_remote_address,
    storage_uri=redis_url,
    app=app,
    default_limits=["200 per day", "20 per hour"]
)

@app.route('/weather', methods=['GET'])
@limiter.limit("20 per minute")
def get_weather():
    location = request.args.get('location')
    data1 = request.args.get("data1")
    data2 = request.args.get("data2")

    if not location:
            return jsonify({'ERROR': 'Location parameter is required'}), 400
    
    possible_params = [
        'unitGroup', 'lang', 'elements', 'include', 'options','iconSet',
        'degreeDayMethod', 'timezone', 'maxDistance', 'maxStations',
        'altitudeDifference', 'locationNames', 'forecastBasisDate',
        'forecastBasisDay',
        'degreeDayInverse', 'degreeDayTempBase',
        'degreeDayStartDate', 'degreeDayStartDate', 'degreeDayTempFix',
        'degreeDayTempMaxThreshold'
    ]
    params = {param: request.args.get(param) for param in possible_params if request.args.get(param)}

    request_url = f"{BASE_URL}{location}"
    if data1:
        request_url += f"/{data1}"
        if data2:
            request_url += f"/{data2}"

    request_url += f"?key={api_key}"
    for param, value in params.items():
        if value:
            request_url += f"&amp;{param}={value}"

    cache_key = f"weather:{location}:{data1}:{data2}:" + "&".join(f"{k}={v}" for k, v in params.items())
    
    cached_data = redis_client.get(cache_key)
    if cached_data:
        return jsonify(json.loads(cached_data))
    
    try:
        response = requests.get(request_url, headers={'Accept': 'application/json'})

        if response.status_code == 429:
            return jsonify({'ERROR': 'request limit exceeded'}), response.status_code
        
        if response.status_code != 200:
            return jsonify({'ERROR': f'HTTP Error: {response.status_code}'}), response.status_code

        if not response.text:
            return jsonify({'ERROR': 'Empty response'}), response.status_code
        
        try:
            weather_data = response.json()
            redis_client.setex(cache_key, TTL, json.dumps(weather_data))
            return weather_data
        
        except ValueError as json_err:
                logging.error("Failed to decode JSON: %s", json_err)
                logging.error("Response text: %s", response.text)
                return jsonify({'ERROR': 'Failed to decode JSON', 'response_text': response.text}), 500

    except requests.exceptions.HTTPError as http_err:
        logging.error(f"HTTP error occurred: {http_err}")
        return jsonify({'ERROR': response.json().get('message', 'Something went wrong')}), response.status_code
    except requests.exceptions.ConnectionError:
        logging.error("Connection error occurred.")
        return jsonify({'ERROR': 'Connection error. Please check your internet connection.'}), 503
    except requests.exceptions.Timeout:
        logging.error("Request timed out.")
        return jsonify({'ERROR': 'Request timed out. Please try again later.'}), 504
    except requests.exceptions.RequestException as err:
        logging.error(f"An error occurred: {err}")
        return jsonify({'ERROR': 'An error occurred while processing your request.'}), 500
    except Exception as e:
        logging.error(f"Unexpected error: {e}")
        return jsonify({'ERROR': 'An unexpected error occurred.'}), 500

if __name__ == '__main__':
    app.run(debug=True)
