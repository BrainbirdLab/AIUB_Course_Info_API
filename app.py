import aiohttp
import asyncio
from fastapi import FastAPI, Form
from typing_extensions import Annotated
from datetime import datetime
from bs4 import BeautifulSoup
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
    return {'success': True, 'message': random_emoji}



@app.post('/')
async def forward_request(UserName: Annotated[str, Form(...)], Password: Annotated[str, Form(...)]):

    print('Processing request...')

    url = 'https://portal.aiub.edu'

    async with aiohttp.ClientSession() as session:
        async with session.post(url, data={'UserName': UserName, 'Password': Password}) as resp:
            if resp.status != 200:
                return {'success': False, 'message': 'Error in request'}

            if 'https://portal.aiub.edu/Student' not in str(resp.url):
                return {'success': False, 'message': 'Invalid username or password'}
            
            if 'Student/Tpe/Start' in str(resp.url):
                print('Evaluation pending')
                #return flask.Response(json.dumps({'success': False, 'message': 'TPE Evaluation pending on portal'}), status=401, mimetype='application/json')
                return {'success': False, 'message': 'TPE Evaluation pending on portal'}

            print('Login successful')

            async with session.get('https://portal.aiub.edu/Student') as res:
                
                soup = BeautifulSoup(await res.text(), 'html.parser')
                targets = soup.select("#SemesterDropDown > option")
                User = soup.select_one('.navbar-link').text
                User = User.split(',')[1].strip() + ' ' + User.split(',')[0].strip()
                User = User.title()

                currentSemester = soup.select_one('#SemesterDropDown > option[selected="selected"]').text
                semesterClassRoutine = {}

                tasks = [process_semester(session, target) for target in targets]

                result = await asyncio.gather(getCurricumnData(session), getCompletedCourses(session, currentSemester), *tasks)

                courseMap = result[0]
                completedCourses = result[1][0]
                currentSemesterCourses = result[1][1]
                preRegisteredCourses = result[1][2]

                for semester in result[2:]:
                    semesterClassRoutine.update(semester)

                # sort the semesters by year
                semesterClassRoutine = dict(sorted(semesterClassRoutine.items(), key=lambda x: x[0]))

                #iterate over the gradesMap. A student can take a course after completing the prerequisites. And also if he/she has taken the course before, he must have D grade
                unlockedCourses = {}
                for courseCode, course in completedCourses.items():
                    #if student has taken the course before and has D grade, then he/she can take the course again
                    if course['grade'] == 'D':
                        unlockedCourses[courseCode] = {'course_name': course['course_name'], 'credit': courseMap[courseCode]['credit'], 'prerequisites': courseMap[courseCode]['prerequisites'], 'retake': True}


                for courseCode, course in courseMap.items():
                        
                        if courseCode in completedCourses:
                            completedCourses[courseCode]['credit'] = course['credit']
                            continue
                        # if course code has '#' or '*' then skip
                        if '#' in courseCode or '*' in courseCode:
                            continue
                        if course['course_name'] == 'INTERNSHIP':
                            continue
                        #if the course is already unlocked, then skip it
                        if courseCode in unlockedCourses:
                            continue
                        #if the course is in the current semester, but has not been dropped, then skip it
                        if courseCode in currentSemesterCourses and currentSemesterCourses[courseCode]['grade'] not in ['W', 'I']:
                            continue
                        #if the course is in the pre-registered courses, then add it to the unlocked courses
                        if courseCode in preRegisteredCourses:
                            unlockedCourses[courseCode] = {'course_name': course['course_name'], 'credit': course['credit'], 'prerequisites': course['prerequisites'], 'retake': False}
                            continue
            
                        prerequisites = course['prerequisites']
                        #if the course has no prerequisites, then it is unlocked
                        if len(prerequisites) == 0:
                            unlockedCourses[courseCode] = {'course_name': course['course_name'], 'credit': course['credit'], 'prerequisites': course['prerequisites'], 'retake': False}
                            continue
                        #iterate over the prerequisites. If the student has taken every prerequisite, then the course is unlocked
                        prerequisitesMet = True
                        for prerequisite in prerequisites:
                            if prerequisite not in completedCourses and prerequisite not in currentSemesterCourses:
                                prerequisitesMet = False
                                break
                        if prerequisitesMet:
                            unlockedCourses[courseCode] = {'course_name': course['course_name'], 'credit': course['credit'], 'prerequisites': course['prerequisites'], 'retake': False}
                        
        print('Sending response...')
        return {'success': True, 'message': 'Success', 'result': {'semesterClassRoutine': semesterClassRoutine, 'unlockedCourses': unlockedCourses, 'completedCourses': completedCourses, 'currentSemester': currentSemester, 'user': User}}



async def getCompletedCourses(session, currentSemester: str): #gets all completed and attempted courses from the grade report
    # get the completed courses
    print('Getting completed courses...')
    async with session.get('https://portal.aiub.edu/Student/GradeReport/ByCurriculum') as response:
        soup = BeautifulSoup(await response.text(), 'html.parser')
        rows = soup.select('table:not(:first-child) tr:not(:first-child):has(td:nth-child(3):not(:empty))')
        # first td contains the course code, second td contains the course name, third td contains the grade
        completedCourses = {}
        currentSemesterCourses = {}
        preRegisteredCourses = {}
        for row in rows:
            courseCode = row.select_one('td:nth-child(1)').text.strip()
            courseName = row.select_one('td:nth-child(2)').text.strip()
            results = row.select_one('td:nth-child(3)').text.strip()

            # Use regular expressions to extract the last result
            matches = re.findall(r'\(([^)]+)\)\s*\[([^\]]+)\]', results)

            # Check if there are any matches
            if matches is not None and len(matches) > 0:
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
                completedCourses[courseCode] = {'course_name': courseName, 'grade': grade}
                #print(f'Completed course: {courseCode} {courseName} {grade} {semester}')
            elif grade == '-':
                if semester == currentSemester:
                    currentSemesterCourses[courseCode] = {'course_name': courseName, 'grade': grade}
                    #print(f'Current semester course: {courseCode} {courseName} {grade} {semester}')
                else:
                    preRegisteredCourses[courseCode] = {'course_name': courseName, 'grade': grade}
                    #print(f'Pre-registered course: {courseCode} {courseName} {grade} {semester}')

        return [completedCourses, currentSemesterCourses, preRegisteredCourses]


async def getCurricumnData(session):
    print('Getting curriculum data...')
    # get the curriculum data
    async with session.get('https://portal.aiub.edu/Student/Curriculum') as response:
        soup = BeautifulSoup(await response.text(), 'html.parser')
        targetElements = soup.select('[curriculumid]')
        curricumnID = []
        for target in targetElements:
            # attribute value is the curriculum id
            curricumnID.append(target.attrs['curriculumid'])

        courseMap = {} # will contain the course code as key and {coursename, prerequisit[]} as value

        #for ID in curricumnID:
        # use asyncio to process the curriculums
        tasks = [process_curriculum(ID, session) for ID in curricumnID]
        results = await asyncio.gather(*tasks)
        for result in results:
            courseMap.update(result)

        return courseMap


async def process_curriculum(ID: str, session):
    # request the getCurricumnLink?IDd=curriculumId
    courseMap = {}
    #print(f'Getting data for curriculum https://portal.aiub.edu/Common/Curriculum?ID={ID}')
    async with session.get(f'https://portal.aiub.edu/Common/Curriculum?ID={ID}') as response:
        soup = BeautifulSoup(await response.text(), 'html.parser')
        table = soup.select('.table-bordered tr:not(:first-child)')
        #print(f'{len(table)} courses extracted')

        for course in table:
            #print(course)
            courseCode = course.select_one('td:nth-child(1)').text.strip()
            courseName = course.select_one('td:nth-child(2)').text.strip()
            credit = course.select_one('td:nth-child(3)').text.strip()
            # credit is 3 0 0 0, 1 1 0 0 format. Split it, Sort it and get the largest number as credit
            credit = sorted([int(c) for c in credit.split(' ')], reverse=True)[0]
            prerequisites = [li.text.strip() for li in course.select('td:nth-child(4) li')]
            courseMap[courseCode] = {'course_name': courseName, 'credit': credit, 'prerequisites': prerequisites}

        return courseMap


async def process_semester(session, target):
    semester = {}
    match = re.search(r'q=(.*)', target.attrs['value'])
    
    if match is not None and len(match.groups()) > 0:
        rq_url = 'https://portal.aiub.edu/Student/Registration?q=' + match.group(1)

        async with session.get(rq_url) as response:
            soup = BeautifulSoup(await response.text(), 'html.parser')
            raw_course_elements = soup.select("table")[1].select("td:first-child")

            if len(raw_course_elements) == 0:
                return semester

            courses_obj = {}
            for course in raw_course_elements:
                if course.text != '':
                    course_name = course.select_one("a").text
                    parsed_course = getCourseDetails(course_name)
                    course_times = course.select("div > span")
                    credit = max(int(c.strip()) for c in course.find_next('td').text.strip().split('-'))

                    course_data = [
                        parseTime(time.text) for time in course_times if 'Time' in time.text
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






def parseTime(timeString):
    try:
        match = re.findall(r'\d{1,2}:\d{1,2}(?:\s?[ap]m|\s?[AP]M)?', timeString)
        dayMap = {'Sun': 'Sunday', 'Mon': 'Monday', 'Tue': 'Tuesday', 'Wed': 'Wednesday', 'Thu': 'Thursday', 'Fri': 'Friday', 'Sat': 'Saturday'}
        class_type = re.search(r'\((.*?)\)', timeString).group(1)
        day = dayMap[re.search(r'(Sun|Mon|Tue|Wed|Thu|Fri|Sat)', timeString).group()]
        room = re.search(r'Room: (.*)', timeString).group(1)
        start_time, end_time = match[0], match[1]
        start_time_obj = ''
        end_time_obj = ''
        #if time contains am/pm or AM/PM
        if "am" in start_time.lower() or "pm" in start_time.lower():
            start_time_obj = datetime.strptime(start_time, '%I:%M %p')
        else:
            start_time_obj = datetime.strptime(start_time, '%I:%M')
        if "am" in end_time.lower() or "pm" in end_time.lower():
            end_time_obj = datetime.strptime(end_time, '%I:%M %p')
        else:
            end_time_obj = datetime.strptime(end_time, '%I:%M')

        start_time_formatted = start_time_obj.strftime('%I:%M %p')
        end_time_formatted = end_time_obj.strftime('%I:%M %p')
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


def getCourseDetails(course):

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