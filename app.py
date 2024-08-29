import aiohttp
import asyncio
from fastapi import FastAPI, Form
from datetime import datetime
from typing_extensions import Annotated
from bs4 import BeautifulSoup, Tag
from datetime import datetime
import os
import re
import random
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()

client_url = os.environ.get('CLIENT_URL')

print(f'Client url: {client_url}')

# allow client url to access the api
@app.middleware("http")
async def cors(request, call_next):
    response = await call_next(request)
    response.headers["Access-Control-Allow-Origin"] = client_url
    return response

default_parser = 'html.parser'

emojis = {
    '😊',
    '😉',
    '😎',
    '😍',
    '😘',
    '😗',
    '😙',
    '👾',
    '👽',
    '👻',
    '👺',
    '🐳',
    '😁',
    '😆',
    '😑',
    '😐',
    '😪',
    '😴',
    '😖',
    '😞',
    '😭',
    '😢',
    '😵',
    '😵‍💫',
    '😷',
    '🥺',
    '🥹'
}



@app.get('/')
async def home():
    #return a random emoji
    random_emoji = random.choice(list(emojis))
    return {'Client': client_url, 'message': f'Version 2: {random_emoji}'}



@app.post('/')
async def forward_request(user_name: str = Annotated[str, Form(...)], password: str = Annotated[str, Form(...)]):

    print('Processing request...')

    url = 'https://portal.aiub.edu'

    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(url, data={'UserName': user_name, 'Password': password}) as resp:
                if resp.status != 200:
                    return {'success': False, 'message': 'Error in request'}
                
                print('Checking response...')

                if 'https://portal.aiub.edu/Student' not in str(resp.url):
                    return {'success': False, 'message': 'Invalid username or password - ' + str(resp.url)}
                
                if 'Student/Tpe/Start' in str(resp.url):
                    print('Evaluation pending')
                    return {'success': False, 'message': 'TPE Evaluation pending on portal'}

                print('Login successful')

                async with session.get('https://portal.aiub.edu/Student') as res:
                    
                    soup = BeautifulSoup(await res.text(), default_parser)
                    targets = soup.select("#SemesterDropDown > option")
                    user = soup.select_one('.navbar-link').text
                    # if user has , in his name, then split it by , and then reverse it
                    if ',' in user:
                        user = user.split(',')
                        user = user[1].strip() + ' ' + user[0].strip()

                    user = user.title()

                    current_semester = soup.select_one('#SemesterDropDown > option[selected="selected"]').text
                    semester_class_routine = {}

                    tasks = [process_semester(session, target) for target in targets]

                    result = await asyncio.gather(get_curricumn_data(session), get_completed_courses(session, current_semester), *tasks)

                    course_map = result[0]
                    completed_courses = result[1][0]
                    current_semester_courses = result[1][1]
                    pre_registered_courses = result[1][2]

                    for semester in result[2:]:
                        semester_class_routine.update(semester)

                    # sort the semesters by year
                    semester_class_routine = dict(sorted(semester_class_routine.items(), key=lambda x: x[0]))

                    #iterate over the gradesMap. A student can take a course after completing the prerequisites. And also if he/she has taken the course before, he must have D grade
                    unlocked_courses = {}
                    for course_code, course in completed_courses.items():
                        #if student has taken the course before and has D grade, then he/she can take the course again
                        if course['grade'] == 'D':
                            unlocked_courses[course_code] = {'course_name': course['course_name'], 'credit': course_map[course_code]['credit'], 'prerequisites': course_map[course_code]['prerequisites'], 'retake': True}

                    completed_courses, unlocked_courses = post_process(course_map, completed_courses, current_semester_courses, pre_registered_courses, unlocked_courses)

                            
                print('Sending response...')
                return {'success': True, 'message': 'Success', 'result': { 'semesterClassRoutine': semester_class_routine, 'unlockedCourses': unlocked_courses, 'completedCourses': completed_courses, 'preregisteredCourses': pre_registered_courses, 'currentSemester': current_semester, 'user': user}}
        except Exception as e:
            print(e)
            return {'success': False, 'message': 'Error in request'}

def is_course_code_skippable(course_code: str) -> bool:
    return '#' in course_code or '*' in course_code

def is_in_current_semester(course_code: str, course: dict, current_semester_courses: dict) -> bool:
    return (
        course_code in current_semester_courses and
        course["course_name"] == current_semester_courses[course_code]["course_name"] and
        current_semester_courses[course_code]['grade'] not in ['W', 'I', 'UW']
    )

def is_course_unlocked(prerequisites: list, completed_courses: dict, current_semester_courses: dict) -> bool:
    if not prerequisites:
        return True
    return all(
        prerequisite in completed_courses or prerequisite in current_semester_courses
        for prerequisite in prerequisites
    )

def post_process(course_map, completed_courses, current_semester_courses, pre_registered_courses, unlocked_courses):
    for course_code, course in course_map.items():
        if course_code in completed_courses:
            completed_courses[course_code]['credit'] = course['credit']
            continue
        if is_course_code_skippable(course_code):
            continue
        if course['course_name'] == 'INTERNSHIP':
            continue
        if course_code in unlocked_courses:
            continue
        if is_in_current_semester(course_code, course, current_semester_courses):
            continue
        if course_code in pre_registered_courses:
            unlocked_courses[course_code] = {
                'course_name': course['course_name'],
                'credit': course['credit'],
                'prerequisites': course['prerequisites'],
                'retake': False
            }
            continue
        
        if is_course_unlocked(course['prerequisites'], completed_courses, current_semester_courses):
            unlocked_courses[course_code] = {
                'course_name': course['course_name'],
                'credit': course['credit'],
                'prerequisites': course['prerequisites'],
                'retake': False
            }

    return completed_courses, unlocked_courses




async def get_completed_courses(session: aiohttp.ClientSession, current_semester: str): #gets all completed and attempted courses from the grade report
    # get the completed courses
    print('Getting completed courses...')
    async with session.get('https://portal.aiub.edu/Student/GradeReport/ByCurriculum') as response:
        soup = BeautifulSoup(await response.text(), default_parser)
        rows = soup.select('table:not(:first-child) tr:not(:first-child):has(td:nth-child(3):not(:empty))')
        # first td contains the course code, second td contains the course name, third td contains the grade
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

            #print (f'{courseCode} {courseName} {grade} {semester}')
            if grade in ['A+', 'A', 'B+', 'B', 'C+', 'C', 'D+', 'D', 'F']:
                completed_courses[course_code] = {'course_name': course_name, 'grade': grade}
                #print(f'Completed course: {courseCode} {courseName} {grade} {semester}')
            elif grade == '-':
                if semester == current_semester:
                    current_semester_courses[course_code] = {'course_name': course_name, 'grade': grade}
                    #print(f'Current semester course: {courseCode} {courseName} {grade} {semester}')
                else:
                    pre_registered_courses[course_code] = {'course_name': course_name, 'grade': grade}
                    #print(f'Pre-registered course: {courseCode} {courseName} {grade} {semester}')

        return [completed_courses, current_semester_courses, pre_registered_courses]


async def get_curricumn_data(session: aiohttp.ClientSession):
    print('Getting curriculum data...')
    # get the curriculum data
    async with session.get('https://portal.aiub.edu/Student/Curriculum') as response:
        soup = BeautifulSoup(await response.text(), default_parser)
        target_elements = soup.select('[curriculumid]')
        curricumn_id = []
        for target in target_elements:
            # attribute value is the curriculum id
            curricumn_id.append(target.attrs['curriculumid'])

        course_map = {} # will contain the course code as key and {coursename, prerequisit[]} as value

        #for ID in curricumnID:
        # use asyncio to process the curriculums
        tasks = [process_curriculum(ID, session) for ID in curricumn_id]
        results = await asyncio.gather(*tasks)
        for result in results:
            course_map.update(result)

        return course_map


async def process_curriculum(id: str, session: aiohttp.ClientSession):
    # request the getCurricumnLink?IDd=curriculumId
    course_map = {}
    #print(f'Getting data for curriculum https://portal.aiub.edu/Common/Curriculum?ID={ID}')
    async with session.get(f'https://portal.aiub.edu/Common/Curriculum?ID={id}') as response:
        soup = BeautifulSoup(await response.text(), default_parser)
        table = soup.select('.table-bordered tr:not(:first-child)')
        #print(f'{len(table)} courses extracted')

        for course in table:
            #print(course)
            course_code = course.select_one('td:nth-child(1)').text.strip()
            course_name = course.select_one('td:nth-child(2)').text.strip()
            credit = course.select_one('td:nth-child(3)').text.strip()
            # credit is 3 0 0 0, 1 1 0 0 format. Split it, Sort it and get the largest number as credit
            credit = sorted([int(c) for c in credit.split(' ')], reverse=True)[0]
            prerequisites = [li.text.strip() for li in course.select('td:nth-child(4) li')]
            course_map[course_code] = {'course_name': course_name, 'credit': credit, 'prerequisites': prerequisites}

        return course_map


async def process_semester(session: aiohttp.ClientSession, target: Tag):
    semester = {}
    match = re.search(r'q=(.*)', target.attrs['value'])
    
    if match is not None and len(match.groups()) < 1:
        return
    
    rq_url = 'https://portal.aiub.edu/Student/Registration?q=' + match.group(1)

    async with session.get(rq_url) as response:
        soup = BeautifulSoup(await response.text(), default_parser)
        raw_course_elements = soup.select("table")[1].select("td:first-child")

        if len(raw_course_elements) == 0:
            return semester

        courses_obj = {}
        for course in raw_course_elements:
            if course.text != '':
                course_name = course.select_one("a").text
                parsed_course = get_course_details(course_name)
                course_times = course.select("div > span")
                credit = max(int(c.strip()) for c in course.find_next('td').text.strip().split('-'))

                course_data = [
                    parse_time(time.text) for time in course_times if 'Time' in time.text
                ]

                for parsed_time in course_data:
                    day = parsed_time['day']
                    if courses_obj.get(day) is None:
                        courses_obj[day] = {}

                    courses_obj[day][parsed_time['time']] = {
                        'course_name': parsed_course['course_name'],
                        'class_id': parsed_course['class_id'],
                        'credit': credit,
                        'section': parsed_course['section'],
                        'type': parsed_time['type'],
                        'room': parsed_time['room']
                    }

        semester[target.text] = courses_obj

    return semester






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
        PM_TIME_FORMAT =  AM_TIME_FORMAT + ' %p'
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


def get_course_details(course: str):
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