import asyncio
import json
import os
import threading
import redis
import requests
from bs4 import BeautifulSoup
from pywebpush import webpush, WebPushException

# Configurations
aiub_home_url = 'https://www.aiub.edu'
default_parser = 'html.parser'

stop_event = threading.Event()

NOTICE_LEN = 8

VAPID_PRIVATE_KEY = os.environ.get('VAPID_PRIVATE_KEY')

# Redis keys
CLIENTS_KEY = "connected_clients_1"  # Redis set to store clients
NOTICE_CHANNEL = "notice_channel_1"  # Redis Pub/Sub channel for notices

REDIS_URL = os.environ.get('REDIS_URL')

# Redis client for storing connected clients and handling Pub/Sub
r = redis.Redis.from_url(REDIS_URL)

redis_error_message = "Error in connecting to Redis"

TIME_TO_WAIT = int(os.environ.get('TIME_TO_WAIT', 60))  # Time to wait in seconds before checking for new notices

VAPID_CLAIMS = {
    "sub": "mailto:fuad.cs22@gmail.com"
}

def check_redis_connection():
    try:
        # Ping Redis to check connection
        if r.ping():
            return True
    except redis.AuthenticationError:
        print("Authentication to Redis failed. Check your password.")
        return False
    except redis.ConnectionError:
        print("Failed to connect to Redis. Check if Redis server is running and accessible.")
        return False
    except Exception as e:
        print(f"An error occurred: {e}")
        return False
    

def format_notice(notice):
    date_str = '.date'
    title = notice.select_one('.card-title').text
    date = ''
    
    link = notice.select_one('a')
    
    if link is not None:
        link = link.get('href')
        if link.startswith('http') or link.startswith('www'):
            title = f"{title}::{link}"
        else:
            title = f"{title}::{aiub_home_url + link}"
        
    if notice.select_one(date_str).text != '':
        date = notice.select_one(date_str).text.strip()
        date = date[:2] + ' ' + date[2:]
        return f"{date}::{title}"
    else:
        return title
    
# Async function to check AIUB notices
async def fetch_new_notice():
    session = requests.Session()
    response = session.get(aiub_home_url)
    soup = BeautifulSoup(response.text, default_parser)

    notice_list = []
    
    global NOTICE_LEN
    
    notices = soup.select('.notice-item')
    if len(notices) > 0:
        # Get the last Count notices, If notices are less than Count, get all minimum notices
        NOTICE_LEN = min(NOTICE_LEN, len(notices))
        for notice in notices[:NOTICE_LEN]:
            formatted_notice = format_notice(notice)
            notice_list.append(formatted_notice)
        
    return notice_list


async def process_new_notices():
    try:
        global NOTICE_LEN
        print("Checking for new notices...")
        new_notices = await fetch_new_notice()
        if new_notices:
            if r.llen(NOTICE_CHANNEL) == 0:
                # Store the new notices in Redis
                r.rpush(NOTICE_CHANNEL, *new_notices)
                # Update the clients with the new notices
                update_clients(new_notices, 'American Internation University - Bangladesh', 'aiub')
            else:
                redis_notices = r.lrange(NOTICE_CHANNEL, 0, -1)
                # decode the notices from bytes to string
                redis_notices = [notice.decode('utf-8') for notice in redis_notices]
                # Check if the new notices are different from the previous notices
                new_notices = list(set(new_notices) - set(redis_notices))
                if len(new_notices) > 0:
                    # Store the new notices in Redis
                    r.lpush(NOTICE_CHANNEL, *new_notices)
                    current_notices_len = r.llen(NOTICE_CHANNEL)
                    if current_notices_len > NOTICE_LEN:
                        r.ltrim(NOTICE_CHANNEL, 0, NOTICE_LEN - 1)
                    # Update the clients with the new notices
                    update_clients(new_notices, 'American Internation University - Bangladesh', 'aiub')

    except Exception as e:
        print(f"Error processing notices: {e}")

async def check_aiub_notices():
    try:
        while not stop_event.is_set():
            connected_clients = r.scard(CLIENTS_KEY)  # Check the number of connected clients
            if connected_clients > 0:
                await process_new_notices()
            await asyncio.sleep(TIME_TO_WAIT) # Check for new notices every TIME_TO_WAIT seconds
    except asyncio.CancelledError:
        print("Task was cancelled")
    finally:
        print("Task ended")

# Function to run in a separate thread
def start_notice_checker():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(check_aiub_notices())
    except asyncio.CancelledError:
        pass
    finally:
        loop.stop()
        loop.close()

# Signal handler to stop the background thread
def signal_handler(_, __):
    try:
        print("Stopping...")
        stop_event.set()  # Signal the thread to stop
        # stop the event loop
        asyncio.get_event_loop().stop()
    except Exception as e:
        print(f"Error stopping: {e}")



def send_web_push(subscription_information, message_body, title: str, data_type: str, data: list):
    
    target = json.dumps({
        "body": message_body,
        "title": title,
        "type": data_type,
        "data": data
    })
    
    return webpush(
        subscription_info=subscription_information,
        data=target,
        vapid_private_key=VAPID_PRIVATE_KEY,
        vapid_claims=VAPID_CLAIMS,
        ttl=86400,  # 1 day TTL (in seconds)
    )


 
 
def update_clients(notices: list, title: str, notice_type: str):
    # Check Redis connection
    if not check_redis_connection():
        return {"status": "error", "message": redis_error_message}
    
    # Get the clients from Redis
    clients = r.smembers(CLIENTS_KEY)  # Redis returns a set of bytes
    
    all_notices = r.lrange(NOTICE_CHANNEL, 0, -1)
    all_notices = [notice.decode('utf-8') for notice in all_notices]

    for client in clients:
        try:
            # Decode and convert the token to dict
            client = json.loads(client.decode('utf-8'))  # Decode from bytes and convert to dict
            # send reverse order of notices
            for notice in reversed(notices):
                send_web_push(client, notice, title, notice_type, all_notices)
        
        except WebPushException as ex:
            # Handle 410 Gone (unregistered client)
            if ex.response.status_code == 410:
                print(f"Client unsubscribed, removing: {client['endpoint']}")
                r.srem(CLIENTS_KEY, json.dumps(client))  # Remove from Redis
            else:
                print(f"Error in sending notification: {ex}")
        
        except Exception as e:
            print(f"General error: {e}")

    return {"status": "success", "message": "Notifications process completed"}
