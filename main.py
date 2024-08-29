from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import os
import re
import concurrent.futures
import json
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()

# Get the port number from the environment variable PORT, if not found, use 5000
PORT = int(os.environ.get('PORT', 5000))

client_url = os.environ.get('CLIENT_URL')

print(f'Client url: {client_url}')

default_parser = 'html.parser'

# Allow CORS to client_url
app.add_middleware(
    CORSMiddleware,
    allow_origins=[client_url],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

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

@app.post("/", response_class=JSONResponse)
async def forward_request(request: Request):

    try:
        print('Processing request...')
        form = await request.form()
        username = form['UserName']
        password = form['Password']
        url = 'https://portal.aiub.edu'
        
        session = requests.Session()
        response = session.post(url, data={'UserName': username, 'Password': password})

        if response.status_code != 200:
            return JSONResponse({'success': False, 'message': 'Error in request'}, status_code=403)

        if 'https://portal.aiub.edu/Student' not in response.url:
            print('Login failed')
            return JSONResponse({'success': False, 'message': 'Invalid username or password'}, status_code=401)

        if 'Student/Tpe/Start' in response.url:
            print('Evaluation pending')
            return JSONResponse({'success': False, 'message': 'TPE Evaluation pending on portal'}, status_code=401)

        print('Login successful')

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
        semester_class_routine = {} # contains all semester info
        course_map = {} # contains all course info
        completed_courses = {} # contains all completed courses info
        current_semester_courses = {} # contains all current semester courses info
        unlocked_courses = {} # contains all unlocked courses info
        pre_registered_courses = {} # contains all pre-registered courses info

        with concurrent.futures.ThreadPoolExecutor() as executor:
            # Execute getCurricumnData concurrently
            course_map_future = executor.submit(get_curricumn_data, cookies, session)

            completed_courses_map_future = executor.submit(get_completed_courses, cookies, session, current_semester)

            # Execute process_semester concurrently for each target
            futures = [executor.submit(process_semester, target, session, cookies) for target in targets]
                        # Wait for getCurricumnData to complete and retrieve the result
            course_map = course_map_future.result()

            # Wait for getGradeReport to complete and retrieve the result
            completed_courses = completed_courses_map_future.result()[0]
            current_semester_courses = completed_courses_map_future.result()[1]
            pre_registered_courses = completed_courses_map_future.result()[2]

            # Wait for process_semester tasks to complete and update semesters
            for future in concurrent.futures.as_completed(futures):
                semester_class_routine.update(future.result())

            
        # Sort the semesters by year
        semester_class_routine = dict(sorted(semester_class_routine.items(), key=lambda x: x[0]))
        
        print('Processing data...')

        # Iterate over the gradesMap. A student can take a course after completing the prerequisites. And also if he/she has taken the course before, he must have D grade
        for course_code, course in completed_courses.items():
            # If student has taken the course before and has D grade, then he/she can take the course again
            if course['grade'] == 'D':
                unlocked_courses[course_code] = {'course_name': course['course_name'], 'credit': course_map[course_code]['credit'], 'prerequisites': course_map[course_code]['prerequisites'], 'retake': True}

        # Add unlocked courses to the unlockedCourses dictionary
        unlocked_courses = add_unlocked_courses(course_map, completed_courses, current_semester_courses, pre_registered_courses, unlocked_courses)

        # Need to get more data like completed courses, credits_completed, credits_remaining, course_completed_count

        result = {'semesterClassRoutine': semester_class_routine, 'unlockedCourses': unlocked_courses, 'completedCourses': completed_courses, 'preregisteredCourses': pre_registered_courses, 'currentSemester': current_semester, 'user': user, 'curriculumncourses': course_map}

        print('Sending response...')

        return JSONResponse({'result': result, 'success': True}, status_code=200)
    
    except Exception as e:
        print(e)
        return JSONResponse({'success': False, 'message': 'Something went wrong'}, status_code=500)
    

def write_current_semester_courses(current_semester_courses):
    with open('currentSemesterCourses.json', 'w') as f:
        json.dump(current_semester_courses, f)

def is_course_code_skippable(course_code: str) -> bool:
    return '#' in course_code or '*' in course_code

def is_course_in_current_semester(course_code: str, course: dict, current_semester_courses: dict) -> bool:
    return (
        course_code in current_semester_courses and
        course["course_name"] == current_semester_courses[course_code]["course_name"] and
        current_semester_courses[course_code]['grade'] not in ['W', 'I']
    )

def add_course_to_unlocked(course_code: str, course: dict, unlocked_courses: dict, retake: bool = False):
    unlocked_courses[course_code] = {
        'course_name': course['course_name'],
        'credit': course['credit'],
        'prerequisites': course['prerequisites'],
        'retake': retake
    }

def is_prerequisites_met(prerequisites: list, completed_courses: dict, current_semester_courses: dict) -> bool:
    return all(
        prerequisite in completed_courses or prerequisite in current_semester_courses
        for prerequisite in prerequisites
    )


def write_current_semester_courses(current_semester_courses):
    with open('currentSemesterCourses.json', 'w') as f:
        json.dump(current_semester_courses, f)

def is_course_eligible(course_code: str, course: dict, completed_courses: dict, current_semester_courses: dict, pre_registered_courses: dict, unlocked_courses: dict) -> bool:
    if course_code in completed_courses:
        completed_courses[course_code]['credit'] = course['credit']
        return False
    if is_course_code_skippable(course_code):
        return False
    if course['course_name'] == 'INTERNSHIP':
        return False
    if course_code in unlocked_courses:
        return False
    if is_course_in_current_semester(course_code, course, current_semester_courses):
        return False
    if course_code in pre_registered_courses:
        add_course_to_unlocked(course_code, course, unlocked_courses, retake=False)
        return False
    return True

def process_course(course_code: str, course: dict, completed_courses: dict, current_semester_courses: dict, unlocked_courses: dict):
    prerequisites = course['prerequisites']
    if not prerequisites or is_prerequisites_met(prerequisites, completed_courses, current_semester_courses):
        add_course_to_unlocked(course_code, course, unlocked_courses, retake=False)

def add_unlocked_courses(course_map, completed_courses, current_semester_courses, pre_registered_courses, unlocked_courses):
    write_current_semester_courses(current_semester_courses)

    for course_code, course in course_map.items():
        if is_course_eligible(course_code, course, completed_courses, current_semester_courses, pre_registered_courses, unlocked_courses):
            process_course(course_code, course, completed_courses, current_semester_courses, unlocked_courses)

    return unlocked_courses



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

    with concurrent.futures.ThreadPoolExecutor() as executor:
        # Execute process_curriculum concurrently
        futures = [executor.submit(process_curriculum, ID, session, cookies) for ID in curricumn_id]

        # Wait for process_curriculum tasks to complete and update courseMap
        for future in concurrent.futures.as_completed(futures):
            course_map.update(future.result())

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


def fetch_response(url, session, cookies):
    response = session.get(url, cookies=cookies)
    return BeautifulSoup(response.text, default_parser)

def extract_courses_from_table(table):
    raw_course_elements = table[1].select("td:first-child")
    courses_obj = {}
    for course in raw_course_elements:
        if course.text:
            course_name = course.select_one("a").text
            parsed_course = get_course_details(course_name)
            courses_obj.update(parse_course_details(course, parsed_course))
    return courses_obj

def parse_course_details(course, parsed_course):
    course_times = course.select("div > span")
    credit = extract_credit(course.findNext('td').text)
    course_details = {}
    for time in course_times:
        if 'Time' in time.text:
            parsed_time = parse_time(time.text)
            if parsed_time['day'] not in course_details:
                course_details[parsed_time['day']] = {}
            course_details[parsed_time['day']][parsed_time['time']] = {
                'course_name': parsed_course['course_name'],
                'class_id': parsed_course['class_id'],
                'credit': credit,
                'section': parsed_course['section'],
                'type': parsed_time['type'],
                'room': parsed_time['room']
            }
    return course_details

def extract_credit(credit_text):
    credit_values = sorted(
        [int(c.strip()) for c in credit_text.split('-')], reverse=True
    )
    return credit_values[0] if credit_values else 0

def process_semester(target, session, cookies):
    semesters = {}
    match = re.search(r'q=(.*)', target.attrs['value'])
    if match and len(match.groups()) > 0:
        try:
            rq_url = f'https://portal.aiub.edu/Student/Registration?q={match.group(1)}'
            soup = fetch_response(rq_url, session, cookies)
            table = soup.select("table")
            courses_obj = extract_courses_from_table(table)
            semesters[target.text] = courses_obj
        except Exception as e:
            print('Error in process_semester: ', e)
    return semesters


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
