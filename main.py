from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import os
import re
import concurrent.futures
import json
import random
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()

# Get the port number from the environment variable PORT, if not found, use 5000
PORT = int(os.environ.get('PORT', 5000))

client_url = os.environ.get('CLIENT_URL')

print(f'Client url: {client_url}')

# Allow CORS to client_url
app.add_middleware(
    CORSMiddleware,
    allow_origins=[client_url],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

def parse_time(timeString):
    try:
        match = re.findall(r'\d{1,2}:\d{1,2}(?:\s?[ap]m|\s?[AP]M)?', timeString)
        day_map = {'Sun': 'Sunday', 'Mon': 'Monday', 'Tue': 'Tuesday', 'Wed': 'Wednesday', 'Thu': 'Thursday', 'Fri': 'Friday', 'Sat': 'Saturday'}
        class_type = re.search(r'\((.*?)\)', timeString).group(1)
        day = day_map[re.search(r'(Sun|Mon|Tue|Wed|Thu|Fri|Sat)', timeString).group()]
        room = re.search(r'Room: (.*)', timeString).group(1)
        start_time, end_time = match[0], match[1]
        start_time_obj = ''
        end_time_obj = ''
        # If time contains am/pm or AM/PM
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

        soup = BeautifulSoup(response.text, 'html.parser')
        targets = soup.select("#SemesterDropDown > option")
        User = soup.select_one('.navbar-link').text

        if ',' in User:
            User = User.split(',')
            User = User[1].strip() + ' ' + User[0].strip()

        User = User.title()

        currentSemester = soup.select_one('#SemesterDropDown > option[selected="selected"]').text
        semesterClassRoutine = {} # contains all semester info
        courseMap = {} # contains all course info
        completedCourses = {} # contains all completed courses info
        currentSemesterCourses = {} # contains all current semester courses info
        unlockedCourses = {} # contains all unlocked courses info
        preRegisteredCourses = {} # contains all pre-registered courses info

        with concurrent.futures.ThreadPoolExecutor() as executor:
            # Execute getCurricumnData concurrently
            courseMap_future = executor.submit(getCurricumnData, cookies, session)

            completedCoursesMap_future = executor.submit(getCompletedCourses, cookies, session, currentSemester)

            # Execute process_semester concurrently for each target
            futures = [executor.submit(process_semester, target, session, cookies) for target in targets]
                        # Wait for getCurricumnData to complete and retrieve the result
            courseMap = courseMap_future.result()

            # Wait for getGradeReport to complete and retrieve the result
            completedCourses = completedCoursesMap_future.result()[0]
            currentSemesterCourses = completedCoursesMap_future.result()[1]
            preRegisteredCourses = completedCoursesMap_future.result()[2]

            # Wait for process_semester tasks to complete and update semesters
            for future in concurrent.futures.as_completed(futures):
                semesterClassRoutine.update(future.result())

            
        # Sort the semesters by year
        semesterClassRoutine = dict(sorted(semesterClassRoutine.items(), key=lambda x: x[0]))
        
        print('Processing data...')

        # Iterate over the gradesMap. A student can take a course after completing the prerequisites. And also if he/she has taken the course before, he must have D grade
        for courseCode, course in completedCourses.items():
            # If student has taken the course before and has D grade, then he/she can take the course again
            if course['grade'] == 'D':
                unlockedCourses[courseCode] = {'course_name': course['course_name'], 'credit': courseMap[courseCode]['credit'], 'prerequisites': courseMap[courseCode]['prerequisites'], 'retake': True}

        # Add unlocked courses to the unlockedCourses dictionary
        unlockedCourses = add_unlocked_courses(courseMap, completedCourses, currentSemesterCourses, preRegisteredCourses, unlockedCourses)

        # Need to get more data like completed courses, credits_completed, credits_remaining, course_completed_count

        result = {'semesterClassRoutine': semesterClassRoutine, 'unlockedCourses': unlockedCourses, 'completedCourses': completedCourses, 'currentSemester': currentSemester, 'user': User, 'curriculumncourses': courseMap}

        print('Sending response...')

        return JSONResponse({'result': result, 'success': True}, status_code=200)
    
    except Exception as e:
        print(e)
        return JSONResponse({'success': False, 'message': 'Something went wrong'}, status_code=500)
    

def add_unlocked_courses(courseMap, completedCourses, currentSemesterCourses, preRegisteredCourses, unlockedCourses):

    # write currentSemesterCourses to a file
    with open('currentSemesterCourses.json', 'w') as f:
        json.dump(currentSemesterCourses, f)

    for courseCode, course in courseMap.items():

        #print(f'Processing course: {course["course_name"]}')

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
        if (courseCode in currentSemesterCourses and course["course_name"] == currentSemesterCourses[courseCode]["course_name"]) and currentSemesterCourses[courseCode]['grade'] not in ['W', 'I']:
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

        #print(f'Added course: {c}')
    
    return unlockedCourses


def getCurricumnData(cookies, session):
    getCurricumnLink = 'https://portal.aiub.edu/Student/Curriculum'
    response = session.get(getCurricumnLink, cookies=cookies)
    soup = BeautifulSoup(response.text, 'html.parser')
    targetElements = soup.select('[curriculumid]')
    curricumnID = []
    for target in targetElements:
        # Attribute value is the curriculum id
        curricumnID.append(target.attrs['curriculumid'])

    courseMap = {}  # Will contain the course code as key and {coursename, prerequisit[]} as value

    with concurrent.futures.ThreadPoolExecutor() as executor:
        # Execute process_curriculum concurrently
        futures = [executor.submit(process_curriculum, ID, session, cookies) for ID in curricumnID]

        # Wait for process_curriculum tasks to complete and update courseMap
        for future in concurrent.futures.as_completed(futures):
            courseMap.update(future.result())

    return courseMap

def process_curriculum(ID: str, session, cookies):
    # Request the getCurricumnLink?IDd=curriculumId
    courseMap = {}
    response = session.get(f'https://portal.aiub.edu/Common/Curriculum?ID={ID}', cookies=cookies)
    soup = BeautifulSoup(response.text, 'html.parser')
    table = soup.select('.table-bordered tr:not(:first-child)')

    for course in table:
        courseCode = course.select_one('td:nth-child(1)').text.strip()
        courseName = course.select_one('td:nth-child(2)').text.strip()
        credit = course.select_one('td:nth-child(3)').text.strip()
        credit = sorted([int(c) for c in credit.split(' ')], reverse=True)[0]
        prerequisites = [li.text.strip() for li in course.select('td:nth-child(4) li')]
        courseMap[courseCode] = {'course_name': courseName, 'credit': credit, 'prerequisites': prerequisites}

    return courseMap

def getCompletedCourses(cookies, session, currentSemester: str): 
    url = 'https://portal.aiub.edu/Student/GradeReport/ByCurriculum'
    response = session.get(url, cookies=cookies)
    soup = BeautifulSoup(response.text, 'html.parser')
    rows = soup.select('table:not(:first-child) tr:not(:first-child):has(td:nth-child(3):not(:empty))')

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

        if grade in ['A+', 'A', 'B+', 'B', 'C+', 'C', 'D+', 'D', 'F']:
            completedCourses[courseCode] = {'course_name': courseName, 'grade': grade}
        elif grade == '-':
            if semester == currentSemester:
                currentSemesterCourses[courseCode] = {'course_name': courseName, 'grade': grade}
            else:
                preRegisteredCourses[courseCode] = {'course_name': courseName, 'grade': grade}
        
    return [completedCourses, currentSemesterCourses, preRegisteredCourses]


def process_semester(target, session, cookies):
    semesters = {}
    match = re.search(r'q=(.*)', target.attrs['value'])
    if match is not None and len(match.groups()) > 0:
        try:
            rq_url = 'https://portal.aiub.edu/Student/Registration?q=' + match.group(1)
            response = session.get(rq_url, cookies=cookies)
            soup = BeautifulSoup(response.text, 'html.parser')
            table = soup.select("table")
            rawCourseElements = table[1].select("td:first-child")
            coursesObj = {}
            for course in rawCourseElements:
                if course.text != '':
                    courseName = course.select_one("a").text
                    parsedCourse = getCourseDetails(courseName)
                    courseTimes = course.select("div > span")
                    credit = course.findNext('td').text.strip()
                    credit = sorted([int(c.strip()) for c in credit.split('-')], reverse=True)[0]
                    for time in courseTimes:
                        if 'Time' not in time.text:
                            continue
                        parsedTime = parseTime(time.text)
                        if coursesObj.get(parsedTime['day']) is None:
                            coursesObj[parsedTime['day']] = {}
                        coursesObj[parsedTime['day']][parsedTime['time']] = {'course_name': parsedCourse['course_name'], 'class_id': parsedCourse['class_id'], 'credit': credit, 'section': parsedCourse['section'], 'type': parsedTime['type'], 'room': parsedTime['room']}
            semesters[target.text] = coursesObj
        except Exception as e:
            print('Error in process_semester: ', e)
    return semesters


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



if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, port=PORT)