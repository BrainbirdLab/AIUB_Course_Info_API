# This is a proxy server that will forward requests to the provided url and return the response to the client

import requests
import flask
from flask_cors import CORS, cross_origin
from bs4 import BeautifulSoup
from datetime import datetime
import os
import re
import concurrent.futures
import json
from dotenv import load_dotenv

load_dotenv()

app = flask.Flask(__name__)
#get the port number from the environment variable PORT, if not found, use 5000
PORT = int(os.environ.get('PORT', 5000))

client_url = os.environ.get('CLIENT_URL')

print(f'Client url: {client_url}')

# allow CORS to client_url
cors = CORS(app, resources={r"/": {"origins": client_url}})

def parseTime(timeString):

    match = re.findall(r'\d{1,2}:\d{1,2}(?:\s?[ap]m|\s?[AP]M)?', timeString)
    dayMap = {'Sun': 'Sunday', 'Mon': 'Monday', 'Tue': 'Tuesday', 'Wed': 'Wednesday'}
    class_type = re.search(r'\((.*?)\)', timeString).group(1)
    day = dayMap[re.search(r'(Sun|Mon|Tue|Wed)', timeString).group()]
    room = re.search(r'Room: (.*)', timeString).group(1)

    try:
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

    if match:
        class_id = match.group(1)
        course_name = match.group(2).title()
        section = match.group(4) if match.group(4) else match.group(3)
        return {"class_id": class_id, "course_name": course_name, "section": section}
    else:
        print("Course not found in the string:", course)
        return {"class_id": "", "course_name": "", "section": ""}


@app.route('/', methods=['GET'])
def home():
    return "<h1>Course Details API</h1><p>This site is a prototype API for course details.</p>"


def process_semester(target, session, cookies):
    semesters = {}
    match = re.search(r'q=(.*)', target.attrs['value'])
    if match:
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
                for time in courseTimes:
                    if 'Time' not in time.text:
                        continue
                    parsedTime = parseTime(time.text)
                    if coursesObj.get(parsedTime['day']) == None:
                        coursesObj[parsedTime['day']] = {}
                    coursesObj[parsedTime['day']][parsedTime['time']] = {'course_name': parsedCourse['course_name'], 'class_id': parsedCourse['class_id'], 'section': parsedCourse['section'], 'type': parsedTime['type'], 'room': parsedTime['room']}
        semesters[target.text] = coursesObj
    return semesters


def process_curriculum(ID: str, session, cookies):
    # request the getCurricumnLink?IDd=curriculumId
    courseMap = {}
    #print(f'Getting data for curriculum https://portal.aiub.edu/Common/Curriculum?ID={ID}')
    response = session.get(f'https://portal.aiub.edu/Common/Curriculum?ID={ID}', cookies=cookies)
    soup = BeautifulSoup(response.text, 'html.parser')
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


def getCurricumnData(cookies, session):
    getCurricumnLink = 'https://portal.aiub.edu/Student/Curriculum'
    response = session.get(getCurricumnLink, cookies=cookies)
    soup = BeautifulSoup(response.text, 'html.parser')
    targetElements = soup.select('[curriculumid]')
    curricumnID = []
    for target in targetElements:
        # attribute value is the curriculum id
        curricumnID.append(target.attrs['curriculumid'])

    #print(curricumnID)

    courseMap = {} # will contain the course code as key and {coursename, prerequisit[]} as value

    #for ID in curricumnID:
    # use multithreading to process the curriculums
    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = [executor.submit(process_curriculum, ID, session, cookies) for ID in curricumnID]
        for future in concurrent.futures.as_completed(futures):
            courseMap.update(future.result())

    return courseMap


def getGradeReport(cookies, session):
    url = 'https://portal.aiub.edu/Student/GradeReport/ByCurriculum'
    response = session.get(url, cookies=cookies)
    soup = BeautifulSoup(response.text, 'html.parser')
    rows = soup.select('table:not(:first-child) tr:not(:first-child)')
    # first td contains the course code, second td contains the course name, third td contains the grade
    grades = {}
    for row in rows:
        courseCode = row.select_one('td:nth-child(1)').text.strip()
        courseName = row.select_one('td:nth-child(2)').text.strip()
        grade = row.select_one('td:nth-child(3)').text.strip()
        grades[courseCode] = {'course_name': courseName, 'grade': grade}
    return grades



@app.route('/', methods=['POST'])
@cross_origin(supports_credentials=True)
def forward_request():
    username = flask.request.form['UserName']
    password = flask.request.form['Password']
    url = 'https://portal.aiub.edu'
    
    session = requests.Session()
    response = session.post(url, data={'UserName': username, 'Password': password})

    if response.status_code != 200:
        return flask.Response('Error in request', status='403', mimetype='text/html')

    if 'https://portal.aiub.edu/Student' not in response.url:
        return flask.Response('Invalid username or password', status='401', mimetype='text/html')

    print('Login successful')

    response = session.get('https://portal.aiub.edu/Student')
    cookies = session.cookies.get_dict()

    soup = BeautifulSoup(response.text, 'html.parser')
    targets = soup.select("#SemesterDropDown > option")
    User = soup.select_one('.navbar-link').text
    User = User.split(',')[1].strip() + ' ' + User.split(',')[0].strip()
    User = User.title()

    semesters = {}
    courseMap = {}
    gradesMap = {}

    with concurrent.futures.ThreadPoolExecutor() as executor:
        # Execute getCurricumnData concurrently
        courseMap_future = executor.submit(getCurricumnData, cookies, session)

        gradesMap_future = executor.submit(getGradeReport, cookies, session)

        # Execute process_semester concurrently for each target
        futures = [executor.submit(process_semester, target, session, cookies) for target in targets]

        # Wait for getCurricumnData to complete and retrieve the result
        courseMap = courseMap_future.result()

        # Wait for getGradeReport to complete and retrieve the result
        gradesMap = gradesMap_future.result()

        # Wait for process_semester tasks to complete and update semesters
        for future in concurrent.futures.as_completed(futures):
            semesters.update(future.result())

    print('Returning response')

    result = {'semesters': semesters, 'courseMap': courseMap, 'gradesMap': gradesMap, 'user': User}

    return flask.jsonify(result)


if __name__ == '__main__':
    from waitress import serve
    print(f'Server started on port {PORT}')
    serve(app, host='0.0.0.0', port=PORT)
