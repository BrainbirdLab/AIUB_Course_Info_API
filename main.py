# This is a proxy server that will forward requests to the provided url and return the response to the client

import requests
import flask
from flask_cors import CORS, cross_origin
from bs4 import BeautifulSoup
from datetime import datetime
import os
import re

app = flask.Flask(__name__)
#get the port number from the environment variable PORT, if not found, use 5000
PORT = int(os.environ.get('PORT', 5000))

# enable CORS for all domains
CORS(app, support_credentials=True)

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
    match = re.match("^([0-9]+)-([A-Za-z0-9()\&\.\s]+) \[([A-Z0-9]+)\]$", course)

    if match:
        course_id = match.group(1)
        course_name = match.group(2)
        course_name = course_name.title()
        section = match.group(3)
        return {"course_id": course_id, "course_name": course_name, "section": section}
    else:
        print("Course not found in the string.", course)
        return {"course_id": "", "course_name": "", "section": ""}

@app.route('/', methods=['GET'])
def home():
    return ':)'

# get the username, password from the request and forward the request to its destination
@app.route('/', methods=['POST'])
@cross_origin(supports_credentials=True)
def forward_request():
    print('Proxy request recieved')
    username = flask.request.form['UserName']
    password = flask.request.form['Password']
    url = 'https://portal.aiub.edu'
    
    session = requests.Session()

    response = session.post(url, data={'UserName': username, 'Password': password})

    if response.status_code != 200:
        # if the request is not successful, return the error with the status code
        return flask.Response('Error in request', status='403', mimetype='text/html')

    if response.url != 'https://portal.aiub.edu/Student/Home/Index/5':
        # if the login is not successful, return the error with the status code
        return flask.Response('Invalid username or password', status='401', mimetype='text/html')

    print('Login successful')

    cookies = session.cookies.get_dict()

    soup = BeautifulSoup(response.text, 'html.parser')
    targets = soup.select("#SemesterDropDown > option")
    User = soup.select_one('.navbar-link').text
      
    semesters = {}
 
    for target in targets:
        semesters[target.text] = []
        # print('Semester: ', target.text)
        #make a request for each semester, send the cookies and get the response
        match = re.search(r'q=(.*)', target.attrs['value'])
        if match:
            rq_url = 'https://portal.aiub.edu/Student/Registration?q=' + match.group(1)
            response = session.get(rq_url,  cookies=cookies)
            soup = BeautifulSoup(response.text, 'html.parser')
            table = soup.select("table")

            rawCourseElements = table[1].select("td:first-child")

            coursesObj = {}

            for course in rawCourseElements:
                if course.text != '':
                    #The course name from the DOM
                    courseName = course.select_one("a").text
                    parsedCourse = getCourseDetails(courseName)
                    #The time from the DOM 
                    courseTimes = course.select("div > span")

                    for time in courseTimes:
                        parsedTime = parseTime(time.text)
                        if coursesObj.get(parsedTime['day']) == None:
                            coursesObj[parsedTime['day']] = {}

                        coursesObj[parsedTime['day']][parsedTime['time']] = {'course_name': parsedCourse['course_name'], 'course_id': parsedCourse['course_id'], 'section': parsedCourse['section'], 'type': parsedTime['type'], 'room': parsedTime['room']}

            #print('Courses by semester: ', coursesBySemester)
        else:
            return flask.Response('Error in request', status='403', mimetype='text/html')
        #print('Adding on Semester: ', target.text, ' => ', coursesArray)
        semesters[target.text] = coursesObj

    print('Returning response')
    #print(semesters)

    return flask.jsonify({'data': semesters, 'user': f'{User} [{username}]'})

    
if __name__ == '__main__':
    from waitress import serve
    print(f'Server started on port {PORT}')
    serve(app, host='0.0.0.0', port=PORT)
