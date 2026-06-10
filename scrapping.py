
import os
import csv
import time
import random
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse

# ==================== CONFIGURATION ====================
CSV_FILE = "movies.csv"
DOWNLOADS_DIR = "downloads"
HARD_STOP_SECONDS = 5 * 60 * 60  # 5 hours total limit (18,000 seconds)
# =======================================================
# Add this under CONFIGURATION if it's missing
CANDIDATE_PROXIES = []


def initialize_csv():
    """Creates a template CSV file if it doesn't exist yet with empty status."""
    if not os.path.exists(CSV_FILE):
        with open(CSV_FILE, mode='w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(["URL", "Status"])
            writer.writerow(["https://film-grab.com/2020/06/26/300/", ""])
        print(f"📄 Created template '{CSV_FILE}'. Add your 4k links to Column A and leave Column B blank.")
        exit()

def read_movie_list():
    """Reads URLs and their processing statuses from the CSV."""
    movies = []
    with open(CSV_FILE, mode='r', newline='', encoding='utf-8') as f:
        reader = csv.reader(f)
        header = next(reader, None)  # Skip header row
        for row in reader:
            if not row or not row[0].strip():
                continue
            url = row[0].strip()
            # If Column B doesn't exist or is empty text, it stays blank (Pending)
            status = row[1].strip() if len(row) > 1 else ""
            movies.append({"url": url, "status": status})
    return movies

def update_csv_status(url_to_update, operational_status):
    """Updates the status column for a specific URL in the CSV file."""
    movies = read_movie_list()
    with open(CSV_FILE, mode='w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(["URL", "Status"])  # Rewrite header
        for movie in movies:
            if movie["url"] == url_to_update:
                writer.writerow([movie["url"], operational_status])
            else:
                writer.writerow([movie["url"], movie["status"]])

def fetch_free_proxies():
    """Fetches a list of free HTTP proxies programmatically from ProxyScrape."""
    base_url = 'https://api.proxyscrape.com/v4/free-proxy-list/get'
    params = {
        'request': 'display_proxies',
        'protocol': 'http',
        'proxy_format': 'ipport',
        'format': 'json',
        'timeout': 5000
    }
    try:
        print("📡 Querying ProxyScrape API for fresh endpoints...")
        response = requests.get(base_url, params=params, timeout=10)
        if response.status_code == 200:
            data = response.json()
            proxies = [f"http://{item['proxy']}" for item in data.get('proxies', [])]
            print(f"⚡ Successfully retrieved {len(proxies)} proxies from API.")
            return proxies
        else:
            print(f"⚠️ Failed to fetch proxies. Status code: {response.status_code}")
            return []
    except Exception as e:
        print(f"❌ Error fetching proxies from API: {e}")
        return []

def verify_proxies(proxy_list):
    """Pings a neutral target to confirm which proxies are currently live."""
    check_pool = proxy_list[:25]
    print(f"🔍 Pre-checking {len(check_pool)} candidates for live connections...")
    live_pool = []
    test_url = "https://www.google.com"
    test_headers = {"User-Agent": "Mozilla/5.0"}

    for proxy in check_pool:
        proxies_dict = {"http": proxy, "https": proxy}
        try:
            response = requests.get(test_url, headers=test_headers, proxies=proxies_dict, timeout=3.5)
            if response.status_code == 200:
                live_pool.append(proxy)
        except Exception:
            pass

    print(f"Verification complete. Found {len(live_pool)} valid proxies active.\n")
    return live_pool

def scrape_movie_images(url, proxy_pool_ref, headers):
    """Processes a single URL, extracts and returns image endpoints, utilizing proxy rotation."""
    url_path = urlparse(url).path.strip('/')
    slug = url_path.split('/')[-1] if url_path else "unknown_movie"
    folder_name = os.path.join(DOWNLOADS_DIR, f"film_grab_{slug}_FULL_RES")

    print(f"\n🎬 Fetching webpage context: {url}...")
    try:
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code != 200:
            print(f"❌ Failed to retrieve the webpage. Status code: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Network connection error reading movie page: {e}")
        return False

    soup = BeautifulSoup(response.text, "html.parser")
    image_urls = set()

    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]
        if "/wp-content/uploads/photo-gallery/" in href and "/thumb/" not in href:
            image_urls.add(href)

    if not image_urls:
        for a_tag in soup.find_all("a", class_="bwg_lightbox", href=True):
            image_urls.add(a_tag["href"])

    if not image_urls:
        print("⚠️ No full-resolution images discovered on this page.")
        return True

    os.makedirs(folder_name, exist_ok=True)
    print(f"📸 Found {len(image_urls)} authentic images. Executing downloads inside '{folder_name}'...")

    failed_urls = [(idx, img_url) for idx, img_url in enumerate(sorted(image_urls), start=1)]
    total_images = len(image_urls)

    session = requests.Session()
    session.headers.update(headers)

    round_count = 1
    last_used_proxy = None
    proxy_pool = proxy_pool_ref["pool"]

    while failed_urls:
        if round_count > 1:
            print(f"\n--- Starting Retry Round {round_count} ({len(failed_urls)} images remaining) ---")
            time.sleep(5)

        next_round_failures = []

        for index, img_url in failed_urls:
            try:
                parsed_url = urlparse(img_url)
                file_name = os.path.basename(parsed_url.path)
                local_filename = os.path.join(folder_name, f"{index:03d}_{file_name}")

                print(f" Downloading [{index}/{total_images}]: {img_url}")

                if not proxy_pool:
                    print("\n🔄 [!] PROXY POOL EXHAUSTED! Fetching a completely fresh batch mid-run...")
                    fresh_candidates = fetch_free_proxies()
                    if not fresh_candidates:
                        fresh_candidates = CANDIDATE_PROXIES
                    proxy_pool = verify_proxies(fresh_candidates)
                    proxy_pool_ref["pool"] = proxy_pool

                selected_proxy = None
                if proxy_pool:
                    available_choices = [p for p in proxy_pool if p != last_used_proxy]
                    if not available_choices:
                        available_choices = proxy_pool

                    selected_proxy = random.choice(available_choices)
                    last_used_proxy = selected_proxy
                    session.proxies = {"http": selected_proxy, "https": selected_proxy}
                    print(f"  [➔] Routed through: {selected_proxy}")
                else:
                    print(f"  [!] No proxies available. Falling back to local IP.")
                    session.proxies = {}

                max_retries = 3
                download_success = False

                for attempt in range(max_retries):
                    try:
                        img_data = session.get(img_url, stream=True, timeout=10)

                        if img_data.status_code == 200:
                            with open(local_filename, 'wb') as handler:
                                for chunk in img_data.iter_content(chunk_size=8192):
                                    handler.write(chunk)
                            download_success = True
                            break

                        elif img_data.status_code == 429:
                            base_wait = (2 ** attempt) * 5
                            jitter = random.uniform(-0.25, 0.25) * base_wait
                            wait_time = max(1, base_wait + jitter)
                            print(f"  [!] Rate limited (429). Waiting {wait_time:.2f}s...")
                            time.sleep(wait_time)

                        elif img_data.status_code == 403:
                            print(f"  [!] Access Forbidden (403). Dropping bad proxy from pool.")
                            if selected_proxy and selected_proxy in proxy_pool:
                                proxy_pool.remove(selected_proxy)
                            break

                        else:
                            print(f"  [!] Error {img_data.status_code}: {img_url}")
                            break
                    except Exception:
                        print(f"  [!] Connection failed. Dropping bad proxy...")
                        if selected_proxy and selected_proxy in proxy_pool:
                            proxy_pool.remove(selected_proxy)
                        break

                if not download_success:
                    next_round_failures.append((index, img_url))

                time.sleep(random.uniform(1.5, 3.5))

            except Exception as e:
                print(f"Error downloading {img_url}: {e}")
                next_round_failures.append((index, img_url))
                time.sleep(random.uniform(1.5, 3.5))

        failed_urls = next_round_failures
        round_count += 1

    print(f"🎉 Completed downloads for this collection.")
    return True

# ==================== MAIN EXECUTION ====================
if __name__ == "__main__":
    initialize_csv()

    # Start global script stopwatch
    script_start_time = time.time()
    movies_processed_counter = 0
    total_processing_time_accumulated = 0.0

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    initial_candidates = fetch_free_proxies()
    if not initial_candidates:
        print("⚠️ API down or rate-limited. Seeding pool with backup candidates...")
        initial_candidates = CANDIDATE_PROXIES

    proxy_sharing_dict = {"pool": verify_proxies(initial_candidates)}

    # Read all lines from the spreadsheet
    movie_list = read_movie_list()

    # 🎯 Filter: Grab ONLY rows where the status is explicitly not "Done" (leaves blank cells as target items)
    pending_movies = [m for m in movie_list if m["status"].lower() != "done"]

    print(f"📋 Total items read from CSV: {len(movie_list)}")
    print(f"⏭️ Skipping {len(movie_list) - len(pending_movies)} rows already marked 'Done'.")
    print(f"🚀 Processing {len(pending_movies)} remaining blank records.\n")

    for index, movie in enumerate(pending_movies, start=1):
        target_url = movie["url"]

        # --- TIME BUDGET PRE-CHECK ---
        current_elapsed_time = time.time() - script_start_time
        remaining_time_budget = HARD_STOP_SECONDS - current_elapsed_time

        # Dynamically predict time cost for the next iteration
        if movies_processed_counter > 0:
            estimated_movie_duration = (total_processing_time_accumulated / movies_processed_counter) * 1.2
        else:
            estimated_movie_duration = 15 * 60  # 15-minute default buffer for the first check

        print(f"\n⏱️ Time Status: {current_elapsed_time/3600:.2f}h elapsed. Budget remaining: {remaining_time_budget/3600:.2f}h.")
        print(f"📊 Estimated time needed for next movie: {estimated_movie_duration/60:.2f} minutes.")

        # Hard boundary safety valve evaluation
        if remaining_time_budget <= estimated_movie_duration:
            print("\n🛑 [SAFE STOP TRIGGERED] Next URL could overshoot the 5-hour limit!")
            print(f"⏳ Remaining budget: {remaining_time_budget:.1f}s | Required cushion: {estimated_movie_duration:.1f}s.")
            print("Shutting down script cleanly. No movies were left half-downloaded.")
            break

        print(f"\n==================================================")
        print(f"🎬 PROCESSING TARGET ({index}/{len(pending_movies)}): {target_url}")
        print(f"==================================================")

        movie_start_stopwatch = time.time()

        # Execute Scraper
        success = scrape_movie_images(target_url, proxy_sharing_dict, headers)

        if success:
            # Change blank status to 'Done' on success
            update_csv_status(target_url, "Done")
            print(f"✅ Flagged status as Done in CSV.")

            movie_run_delta = time.time() - movie_start_stopwatch
            total_processing_time_accumulated += movie_run_delta
            movies_processed_counter += 1
        else:
            print(f"❌ Failed processing: {target_url}. Kept blank for retry later.")

        time.sleep(random.uniform(3, 7))

    final_execution_duration = time.time() - script_start_time
    print(f"\n🏁 Complete. Total elapsed run time: {final_execution_duration/3600:.2f} hours.")
