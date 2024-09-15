import asyncio
import signal
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import os
import re
import json
from dotenv import load_dotenv
import redis
from contextlib import asynccontextmanager

from notice import check_aiub_notices, check_redis_connection, process_new_notices, signal_handler, update_clients, stop_event, redis_error_message, send_web_push

load_dotenv()

# Get the port number from the environment variable PORT, if not found, use 5000
PORT = int(os.environ.get('PORT', 5000))

client_url = os.environ.get('CLIENT_URL')

VAPID_PUBLIC_KEY = os.environ.get('VAPID_PUBLIC_KEY')
VAPID_PRIVATE_KEY = os.environ.get('VAPID_PRIVATE_KEY')

aiub_portal_url = 'https://portal.aiub.edu'
aiub_home_url = 'https://www.aiub.edu'

REDIS_URL = os.environ.get('REDIS_URL')

# Redis keys
CLIENTS_KEY = "connected_clients"  # Redis set to store clients
NOTICE_CHANNEL = "notice_channel"  # Redis Pub/Sub channel for notices

# Redis client for storing connected clients and handling Pub/Sub
r = redis.Redis.from_url(REDIS_URL)

# Configurations
aiub_home_url = 'https://www.aiub.edu'
default_parser = 'html.parser'

# Lifespan context manager to manage the app lifecycle
@asynccontextmanager
async def lifespan(app: FastAPI):
    signal.signal(signal.SIGINT, signal_handler)  # Handle Ctrl+C for clean shutdown
    notice_task = asyncio.create_task(check_aiub_notices())  # Start the background task
    try:
        yield
    finally:
        stop_event.set()  # Stop the background task when shutting down
        notice_task.cancel()  # Cancel the task gracefully
        await notice_task  # Wait for task to complete
        print("Background task stopped")

app = FastAPI(lifespan=lifespan)

# Allow CORS to client_url
app.add_middleware(
    CORSMiddleware,
    allow_origins=[client_url],
    allow_credentials=True,
    allow_methods=["*"],  # Allow all HTTP methods
    allow_headers=["*"],  # Allow all headers
)



@app.get("/")
async def root():
    # return html content
    return HTMLResponse(content="<h2>Wanna join the party? 🎉</h2><br>Contact with us to get involved <a href='mailto:fuad.cs22@gmail.com'>here</a><br><pre>version: 2.0.5</pre>")


@app.get('/getkey')
async def get_key():
    return {"publicKey": VAPID_PUBLIC_KEY}

@app.post('/subscribe')
async def subscribe(subscription: dict):
    try:
        # Add subscription to Redis
        r.sadd(CLIENTS_KEY, json.dumps(subscription))
        
        # send a Thank you notification
        send_web_push(subscription, "You would be updated with the future notifications", "Thank you", "server")
        return {"status": "success", "message": "Subscribed successfully"}
    
    except Exception as e:
        # Handle general exceptions
        print(f"Error in subscription process: {e}")
        return {"status": "error", "message": "Subscription failed"}
    
@app.post('/unsubscribe')
async def unsubscribe(subscription: dict):
    # check Redis connection
    if not check_redis_connection():
        return {"status": "error", "message": redis_error_message}
    
    # Check if the subscription exists in Redis
    if not r.sismember(CLIENTS_KEY, json.dumps(subscription)):
        return {"status": "error", "message": "Subscription not found"}
    
    # Remove subscription from Redis
    r.srem(CLIENTS_KEY, json.dumps(subscription))
    return {"status": "success", "message": "Unsubscribed successfully"}


@app.post('/subscription-status')
async def subscription_status(subscription: dict):
    # Check Redis connection
    if not check_redis_connection():
        return {"status": "error", "message": redis_error_message, "subscribed": False}
    
    # Check if the subscription exists in Redis
    if r.sismember(CLIENTS_KEY, json.dumps(subscription)):
        return {"status": "success", "message": "Subscription exists", "subscribed": True}
    else:
        return {"status": "error", "message": "Subscription not found", "subscribed": False}


# test dev trigger for notification
@app.get('/push/{auth}/{message}')
async def push_notification(_: Request, auth: str, message: str):
    auth_id = os.environ.get('AUTH_ID')
    if auth != auth_id and message == '':
        return {"status": "error", "message": "Unauthorized request"}
    
    return update_clients([message], "Message from developer", 'dev')

@app.get('/notices')
async def get_notices(request: Request):
    print('Request received')
    ref = get_host(request.headers.get('referer'))
    client_host = get_host(client_url)
    
    if ref != client_host:
        return {"status": "error", "message": "Unauthorized request"}
    
    
    # Check Redis connection
    if not check_redis_connection():
        return {"status": "error", "message": redis_error_message}
    
    await process_new_notices()
    
    # Get the notices from Redis
    notices = r.lrange(NOTICE_CHANNEL, 0, -1)
    # Decode the notices from bytes to string
    notices = [notice.decode('utf-8') for notice in notices]
    
    return {"status": "success", "notices": notices}

@app.get("/login")
async def forward_request(request: Request):
    
    ref = request.headers.get('referer')

    # query parameters
    username = request.query_params.get('username')
    password = request.query_params.get('password')

    # Return the streaming response
    return StreamingResponse(event_stream(username, password, ref), media_type="text/event-stream")


@app.get("*")
def catch_all():
    # redirect to the root
    return RedirectResponse(url="/")

def get_host(url: str | None) -> str:
    try:
        if url is None:
            return ''
        if url == '':
            return ''
        return url.split('/')[2]
    except IndexError:
        return ''


async def event_stream(username: str, password: str, ref):
    try:
        
        ref_host = get_host(ref)
        client_host = get_host(client_url)
        
        if ref_host != client_host:
            print(f'Client: {client_host} mismatched with ref: {ref_host}')
            yield f'data: {json.dumps({"status": "error", "message": "Unauthorized request"})}\n\n'
            return
        
        # Notify the client that processing has started
        print('Processing request...')
        yield f'data: {json.dumps({"status": "running", "message": "Processing request..."})}\n\n'

        if username is None or password is None:
            yield f'data: {json.dumps({"status": "error", "message": "Username and password are required"})}\n\n'
            return
        
        # if empty username or password
        if username == '' or password == '':
            yield f'data: {json.dumps({"status": "error", "message": "Username and password are required"})}\n\n'
            return
        
        session = requests.Session()
        response = session.post(aiub_portal_url, data={'UserName': username, 'Password': password})

        if response.status_code != 200:
            print("Error in req")
            yield f'data: {json.dumps({"status": "error", "message": "Error in request"})}\n\n'
            return

        if 'https://portal.aiub.edu/Student' not in response.url:
            # check if captcha is required
            cap_elem = BeautifulSoup(response.text, default_parser).select_one('#captcha')
            if cap_elem is not None and cap_elem.attrs.get('style') != 'display: none':
                print('Captcha required')
                yield f'data: {json.dumps({"status": "error", "message": "Captcha required. Solve it from portal."})}\n\n'
                return
            print('Invalid username or password')
            yield f'data: {json.dumps({"status": "error", "message": "Invalid username or password"})}\n\n'
            return
        
        # Login successful
        print('Login successful')
        yield f'data: {json.dumps({"status": "running", "message": "Logged in to portal"})}\n\n'

        if 'Student/Tpe/Start' in response.url:
            yield f'data: {json.dumps({"status": "error", "message": "TPE Evaluation Pending"})}\n\n'
            return

        response = session.get('https://portal.aiub.edu/Student')
        
        cookies = session.cookies.get_dict()

        soup = BeautifulSoup(response.text, default_parser)
        targets = soup.select("#SemesterDropDown > option")
        user = soup.select_one('.navbar-link').text

        if ',' in user:
            user = user.split(',')
            user = user[1].strip() + ' ' + user[0].strip()

        user = user.title()

        current_semester = soup.select_one('#SemesterDropDown > option[selected="selected"]').text
        semester_class_routine = {}

        # use the following code to run the code synchronously
        yield f'data: {json.dumps({"status": "running", "message": "Getting curriculum data..."})}\n\n'
        course_map = get_curricumn_data(cookies, session)
        
        yield f'data: {json.dumps({"status": "running", "message": "Completed getting curriculum data"})}\n\n'

        
        yield f'data: {json.dumps({"status": "running", "message": "Getting completed courses..."})}\n\n'
        completed_courses, current_semester_courses, pre_registered_courses = get_completed_courses(cookies, session, current_semester)
        
        yield f'data: {json.dumps({"status": "running", "message": "Completed getting completed courses"})}\n\n'

        
        yield f'data: {json.dumps({"status": "running", "message": "Fetching semester data..."})}\n\n'
        for target in targets:
            yield f'data: {json.dumps({"status": "running", "message": "Analyzing: " + target.text})}\n\n'
            semester_class_routine.update(process_semester(target, session, cookies))
        
        yield f'data" {json.dumps({"status": "running", "message": "Completed processing semesters"})}\n\n'

        # Sort the semesters
        semester_class_routine = dict(sorted(semester_class_routine.items(), key=lambda x: x[0]))

        yield f'data: {json.dumps({"status": "running", "message": "Packing all data..."})}\n\n'
        
        result = pack_data(completed_courses, current_semester_courses, pre_registered_courses, semester_class_routine, course_map, user, current_semester)

        print('Data processing complete')
        # send as data: {status: 'complete', result: result}
        yield f'data: {json.dumps({"status": "complete", "result": result})}\n\n'
        return

    except Exception as e:
        print('Error in event_stream:', e)
        yield f"data: {json.dumps({'status': 'error', 'message': str(e)})}\n\n"
        return


def pack_data(completed_courses, current_semester_courses, pre_registered_courses, semester_class_routine, course_map, user, current_semester):

    unlocked_courses = {}

    # Iterate over completed courses
    for course_code, course in completed_courses.items():
        if course['grade'] == 'D':
            unlocked_courses[course_code] = {
                'course_name': course['course_name'],
                'credit': course_map[course_code]['credit'],
                'prerequisites': course_map[course_code]['prerequisites'],
                'retake': True
            }

    unlocked_courses = add_unlocked_courses(course_map, completed_courses, current_semester_courses, pre_registered_courses, unlocked_courses)

    result = {
        'semesterClassRoutine': semester_class_routine,
        'unlockedCourses': unlocked_courses,
        'completedCourses': completed_courses,
        'preregisteredCourses': pre_registered_courses,
        'currentSemester': current_semester,
        'user': user,
        'curriculumncourses': course_map
    }
    
    return result


def add_unlocked_courses(course_map, completed_courses, current_semester_courses, pre_registered_courses, unlocked_courses):

    for course_code, course in course_map.items():
        if should_skip_course(course_code, course, completed_courses, current_semester_courses, pre_registered_courses, unlocked_courses):
            continue

        prerequisites = course['prerequisites']
        if len(prerequisites) == 0 or are_prerequisites_met(prerequisites, completed_courses, current_semester_courses):
            unlocked_courses[course_code] = {'course_name': course['course_name'], 'credit': course['credit'], 'prerequisites': course['prerequisites'], 'retake': False}

    return unlocked_courses

def should_skip_course(course_code, course, completed_courses, current_semester_courses, pre_registered_courses, unlocked_courses):
    if course_code in completed_courses:
        completed_courses[course_code]['credit'] = course['credit']
        return True
    if '#' in course_code or '*' in course_code:
        return True
    if course['course_name'] == 'INTERNSHIP':
        return True
    if course_code in unlocked_courses:
        return True
    if (course_code in current_semester_courses and course["course_name"] == current_semester_courses[course_code]["course_name"]) and current_semester_courses[course_code]['grade'] not in ['W', 'I']:
        return True
    if course_code in pre_registered_courses:
        unlocked_courses[course_code] = {'course_name': course['course_name'], 'credit': course['credit'], 'prerequisites': course['prerequisites'], 'retake': False}
        return True
    return False

def are_prerequisites_met(prerequisites, completed_courses, current_semester_courses):
    for prerequisite in prerequisites:
        if prerequisite not in completed_courses and prerequisite not in current_semester_courses:
            return False
    return True


def get_curricumn_data(cookies, session):
    get_curricumn_link = 'https://portal.aiub.edu/Student/Curriculum'
    response = session.get(get_curricumn_link, cookies=cookies)
    soup = BeautifulSoup(response.text, default_parser)
    target_elements = soup.select('[curriculumid]')
    curricumn_id = []
    for target in target_elements:
        # Attribute value is the curriculum id
        curricumn_id.append(target.attrs['curriculumid'])

    course_map = {}  # Will contain the course code as key and {coursename, prerequisit[]} as value

    for _id in curricumn_id:
        course_map.update(process_curriculum(_id, session, cookies))


    return course_map

def process_curriculum(id: str, session, cookies):
    # Request the getCurricumnLink?IDd=curriculumId
    course_map = {}
    response = session.get(f'https://portal.aiub.edu/Common/Curriculum?ID={id}', cookies=cookies)
    soup = BeautifulSoup(response.text, default_parser)
    table = soup.select('.table-bordered tr:not(:first-child)')

    for course in table:
        course_code = course.select_one('td:nth-child(1)').text.strip()
        course_name = course.select_one('td:nth-child(2)').text.strip()
        credit = course.select_one('td:nth-child(3)').text.strip()
        credit = sorted([int(c) for c in credit.split(' ')], reverse=True)[0]
        prerequisites = [li.text.strip() for li in course.select('td:nth-child(4) li')]
        course_map[course_code] = {'course_name': course_name, 'credit': credit, 'prerequisites': prerequisites}

    return course_map

def get_completed_courses(cookies, session, current_semester: str): 
    url = 'https://portal.aiub.edu/Student/GradeReport/ByCurriculum'
    response = session.get(url, cookies=cookies)
    soup = BeautifulSoup(response.text, default_parser)
    rows = soup.select('table:not(:first-child) tr:not(:first-child):has(td:nth-child(3):not(:empty))')

    completed_courses = {}
    current_semester_courses = {}
    pre_registered_courses = {}

    for row in rows:
        course_code = row.select_one('td:nth-child(1)').text.strip()
        course_name = row.select_one('td:nth-child(2)').text.strip()
        results = row.select_one('td:nth-child(3)').text.strip() 

        # Use regular expressions to extract the last result
        matches = re.findall(r'\(([^)]+)\)\s*\[([^\]]+)\]', results)

        # Check if there are any matches
        if  len(matches) > 0:
            # Get the last match
            last_result = matches[-1]
            # Extract grade and semester from the last result
            semester, grade = last_result
            grade = grade.strip()
            semester = semester.strip()
        else:
            continue

        if grade in ['A+', 'A', 'B+', 'B', 'C+', 'C', 'D+', 'D', 'F']:
            completed_courses[course_code] = {'course_name': course_name, 'grade': grade}
        elif grade == '-':
            if semester == current_semester:
                current_semester_courses[course_code] = {'course_name': course_name, 'grade': grade}
            else:
                pre_registered_courses[course_code] = {'course_name': course_name, 'grade': grade}
        
    return [completed_courses, current_semester_courses, pre_registered_courses]


def process_semester(target, session, cookies):
    semesters = {}
    match = re.search(r'q=(.*)', target.attrs['value'])
    if match is not None and len(match.groups()) > 0:
        try:
            rq_url = 'https://portal.aiub.edu/Student/Registration?q=' + match.group(1)
            response = session.get(rq_url, cookies=cookies)
            soup = BeautifulSoup(response.text, default_parser)
            table = soup.select("table")
            raw_course_elements = table[1].select("td:first-child")
            courses_obj = {}
            for course in raw_course_elements:
                if course.text != '':
                    course_name = course.select_one("a").text
                    parsed_course = get_course_details(course_name)
                    course_times = course.select("div > span")
                    credit = course.findNext('td').text.strip()
                    credit = sorted([int(c.strip()) for c in credit.split('-')], reverse=True)[0]
                    courses_obj = process_course_times(course_times, parsed_course, credit, courses_obj)
            semesters[target.text] = courses_obj
        except Exception as e:
            print('Error in process_semester: ', e)
    return semesters

def process_course_times(course_times, parsed_course, credit, courses_obj):
    for time in course_times:
        if 'Time' not in time.text:
            continue
        parsed_time = parse_time(time.text)
        if courses_obj.get(parsed_time['day']) is None:
            courses_obj[parsed_time['day']] = {}
        courses_obj[parsed_time['day']][parsed_time['time']] = {'course_name': parsed_course['course_name'], 'class_id': parsed_course['class_id'], 'credit': credit, 'section': parsed_course['section'], 'type': parsed_time['type'], 'room': parsed_time['room']}
    return courses_obj


def get_course_details(course):
    match = re.match(r"^(\d+)-(.+?)\s+\[([A-Z0-9]+)\](?:\s+\[([A-Z0-9]+)\])?$", course)
    try:
        if match:
            class_id = match.group(1)
            course_name = match.group(2).title()
            section = match.group(4) if match.group(4) else match.group(3)
            return {"class_id": class_id, "course_name": course_name, "section": section}
        else:
            print("Course not found in the string:", course)
            return {"class_id": "", "course_name": "", "section": ""}
    except IndexError:
        print("Course not found in the string:", course)
        return {"class_id": "", "course_name": "", "section": ""}



def parse_time(time_string: str):
    try:
        match = re.findall(r'\d{1,2}:\d{1,2}(?:\s?[ap]m|\s?[AP]M)?', time_string)
        day_map = {'Sun': 'Sunday', 'Mon': 'Monday', 'Tue': 'Tuesday', 'Wed': 'Wednesday', 'Thu': 'Thursday', 'Fri': 'Friday', 'Sat': 'Saturday'}
        class_type = re.search(r'\((.*?)\)', time_string).group(1)
        day = day_map[re.search(r'(Sun|Mon|Tue|Wed|Thu|Fri|Sat)', time_string).group()]
        room = re.search(r'Room: (.*)', time_string).group(1)
        start_time, end_time = match[0], match[1]
        start_time_obj = ''
        end_time_obj = ''
        #if time contains am/pm or AM/PM
        AM_TIME_FORMAT = '%I:%M'
        PM_TIME_FORMAT = AM_TIME_FORMAT + ' %p'
        if "am" in start_time.lower() or "pm" in start_time.lower():
            start_time_obj = datetime.strptime(start_time, PM_TIME_FORMAT)
        else:
            start_time_obj = datetime.strptime(start_time, AM_TIME_FORMAT)
        if "am" in end_time.lower() or "pm" in end_time.lower():
            end_time_obj = datetime.strptime(end_time, PM_TIME_FORMAT)
        else:
            end_time_obj = datetime.strptime(end_time, AM_TIME_FORMAT)

        start_time_formatted = start_time_obj.strftime(PM_TIME_FORMAT)
        end_time_formatted = end_time_obj.strftime(PM_TIME_FORMAT)
        final_time = f"{start_time_formatted} - {end_time_formatted}"
        data = {
            "type": class_type,
            "time": final_time,
            "day": day,
            "room": room
        }
        return data
    except IndexError:
        print("Time not found in the string.")
