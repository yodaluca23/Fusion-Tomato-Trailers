import json
import flask
import os
from dotenv import load_dotenv
import requests
from bs4 import BeautifulSoup
from flask_caching import Cache

load_dotenv()
app = flask.Flask(__name__)

# Configure caching
cache = Cache(app, config={'CACHE_TYPE': 'redis', 'CACHE_REDIS_URL': os.getenv('REDIS_URL', 'redis://localhost:6379/0')})

def fetch_rotten_tomatoes(query):
    # Format the query for the URL
    url = f"https://www.rottentomatoes.com/search?search={query}"
    
    # Make a GET request to fetch the HTML content
    response = requests.get(url)
    response.raise_for_status()  # Raises an error for bad responses

    # Parse the HTML content
    soup = BeautifulSoup(response.text, 'html.parser')
    
    # Initialize an empty list to hold the results
    results = []

    # Find all relevant search page media rows
    media_rows = soup.find_all('search-page-media-row', {'data-qa': 'data-row'})

    for row in media_rows:
        # Extract details from each media row
        title = row.find('a', {'data-qa': 'info-name'}).text.strip()
        link = row.find('a', {'data-qa': 'thumbnail-link'})['href']
        image_src = row.find('img')['src']
        cast = row['cast'].split(',') if 'cast' in row.attrs else []
        release_year = row.get('release-year', None)
        tomatometer_score = row.get('tomatometer-score', None)
        tomatometer_certified = row.get('tomatometer-is-certified', 'false') == 'true'

        # Append to results
        results.append({
            'title': title,
            'link': link,
            'image_src': image_src,
            'cast': [actor.strip() for actor in cast],
            'release_year': release_year,
            'tomatometer_score': tomatometer_score,
            'tomatometer_certified': tomatometer_certified
        })

    # Return the results as JSON
    return results

# Example usage:
#print(json.dumps(fetch_rotten_tomatoes("Inception"), indent=4))

def fetch_rt_videos(rtPage):

    html_snippet = requests.get(rtPage).text

    # Parse the HTML snippet
    soup = BeautifulSoup(html_snippet, 'html.parser')

    # Find the script tag with the desired id
    json_script = soup.find('script', {'id': 'videos'})

    # Extract and parse the JSON data
    if json_script:
        json_data = json_script.string
        try:
            json_object = json.loads(json_data)  # Parse the JSON string
            return json_object  # Return the JSON object
        except json.JSONDecodeError as e:
            print('Error parsing JSON:', e)
    else:
        print('Script tag with ID "videos" not found.')

@app.route('/health', methods=['GET'])
def health_check():
    return flask.jsonify({"status": "healthy"}), 200

@app.route('/manifest.json', methods=['GET'])
def get_manifest():
    manifest = {
        "id": "yodaluca23.tomato.trailers",
        "name": "Rotten Tomatoes Trailers",
        "author": "yodaluca23",
        "version": "1.0.0",
        "description": "Get Trailers from Rotten Tomatoes.",
        "resources": ["meta"],
        "types": ["movie", "series"],
        "idPrefixes": ["tt"]
    }
    return flask.jsonify(manifest)

@app.route('/meta/<string:media_type>/<string:media_id>', methods=['GET'])
@cache.cached(timeout=2592000, query_string=True)  # Cache for 1 month per media_id
def get_trailer(media_type, media_id):
    if media_type not in ['movie', 'series']:
        return flask.jsonify({"error": "Unsupported media type"}), 400

    media_id = media_id.split(".")[0]  # Remove any file extension if present
    # Extract the IMDb ID from the media_id (e.g., "tt1234567")
    if not media_id.startswith('tt'):
        return flask.jsonify({"error": "Invalid media ID format"}), 400

    # Use TMDB API to get the YouTube trailer link
    tmdb_api_key = os.getenv('TMDB_API_KEY')

    url = f'https://api.themoviedb.org/3/find/{media_id}?external_source=imdb_id'
    #print(f"Fetching TMDB data from: {url}")
    response = requests.get(
        url,
        headers={'Authorization': f'Bearer {tmdb_api_key}'}
    )
    if response.status_code != 200:
        return flask.jsonify({"error": "Failed to fetch data from TMDB"}), 500 
    
    data = response.json()
    #print(json.dumps(data, indent=4))

    data = data.get('movie_results', [])
    #print(json.dumps(data, indent=4))
    tmdb = data[0].get('id', None) if data else None

    if not tmdb:
        return flask.jsonify({"error": "Media not found in TMDB"}), 404

    release_date = data[0].get('release_date')
    title = data[0].get('title')

    rtResults = fetch_rotten_tomatoes(title)
    rtResult = None
    for result in rtResults:
        if result['release_year'] and release_date and result['release_year'] in release_date:
            if result['title'].lower() == title.lower():
                rtResult = result
                break

    if not rtResult:
        return flask.jsonify({"error": "No matching result found in Rotten Tomatoes"}), 404
    
    #print(json.dumps(rtResult, indent=4))

    videos = fetch_rt_videos(rtResult['link'] + "/videos")

    #print(json.dumps(videos, indent=4))

    if not videos:
        return flask.jsonify({"error": "No videos found on Rotten Tomatoes"}), 404

    trailers = []
    for video in videos:
        if video.get("videoType", "") == "TRAILER":
            trailers.append(video)

    formated_trailers = []
    for trailer in trailers:
        formated_trailers.append({
            "trailers": trailer["file"],
            "provider": trailer["title"],
            "thumbnail": trailer["thumbnail"]
        })

    provide = {
        "meta": {
            "id": media_id,
            "type": media_type,
            "name": title,
            "links": formated_trailers
        }
    }

    return flask.jsonify(provide)

#get_trailer("movie", "tt1375666")

# Use for testing purposes, in production you should use a proper web server like Gunicorn or uWSGI
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=6969)
