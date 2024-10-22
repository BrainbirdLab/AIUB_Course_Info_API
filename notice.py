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

NOTICE_LEN = 10  # Number of notices to check for new notices

VAPID_PRIVATE_KEY = os.environ.get('VAPID_PRIVATE_KEY')

# Redis keys
CLIENTS_KEY = "connected_clients_0"  # Redis set to store clients
NOTICE_CHANNEL = "notice_channel_0"  # Redis Pub/Sub channel for notices

REDIS_URL = os.environ.get('REDIS_URL')

# Redis client for storing connected clients and handling Pub/Sub
r = redis.Redis.from_url(REDIS_URL)

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

# print redis connection status
if check_redis_connection():
    print("Connected to Redis")
else:
    print("Error in connecting to Redis")
    

redis_error_message = "Error in connecting to Redis"

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
                inform_clients(new_notices)

    except Exception as e:
        print(f"Error processing notices: {e}")
        

def inform_clients(new_notices):
    redis_notices = r.lrange(NOTICE_CHANNEL, 0, -1)
    # decode the notices from bytes to string
    redis_notices = [notice.decode('utf-8') for notice in redis_notices]
    # Check if the new notices are different from the previous notices
    added_notices = list(set(new_notices) - set(redis_notices))
    changed = len(list(set(new_notices).symmetric_difference(set(redis_notices))))
    if changed != 0:
        # replace the old notices with new notices
        r.delete(NOTICE_CHANNEL)
        r.rpush(NOTICE_CHANNEL, *new_notices)
    if len(added_notices) > 0:
        print("New notices found, informing clients...")
        current_notices_len = r.llen(NOTICE_CHANNEL)
        if current_notices_len > NOTICE_LEN:
            r.ltrim(NOTICE_CHANNEL, 0, NOTICE_LEN - 1)
        # Update the clients with the new notices
        update_clients(added_notices, 'American Internation University - Bangladesh', 'aiub')
    else:
        print("No new notices found")

def send_web_push(subscription_information, message_body, title: str, data_type: str):
    
    target = json.dumps({
        "body": message_body,
        "title": title,
        "type": data_type,
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

    for client in clients:
        try:
            # Decode and convert the token to dict
            client = json.loads(client.decode('utf-8'))  # Decode from bytes and convert to dict
            # send reverse order of notices
            for notice in reversed(notices):
                send_web_push(client, notice, title, notice_type)
        
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
