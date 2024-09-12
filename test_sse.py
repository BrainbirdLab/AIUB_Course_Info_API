
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
import asyncio
import requests

from dotenv import load_dotenv
import os

load_dotenv()

app = FastAPI()


# Get the port number from the environment variable PORT, if not found, use 5000
PORT = int(os.environ.get('PORT', 5000))

client_url = os.environ.get('CLIENT_URL')

print(f'Client url: {client_url}')


# allow client url to access the api
@app.middleware("http")
async def cors(request, call_next):
    response = await call_next(request)
    response.headers["Access-Control-Allow-Origin"] = 'http://127.0.0.1:5678'
    return response

@app.get("/")
def read_root():
    return {"Hello": "World"}



@app.get("/sse")
async def sse(request: Request):
    async def event_generator():
        url = 'https://portal.aiub.edu'

        # query parameters
        username = request.query_params.get('username')
        password = request.query_params.get('password')

        print(f'Username: {username}')
        print(f'Password: {password}')

        post_data = {
            'UserName': username,
            'Password': password
        }

        session = requests.Session()
        print('Posting data to the server')
        yield "data: logging in\n\n"

        response = session.post(url, data=post_data)

        if response.status_code != 200:
            print('Login failed')
            yield "data: login failed\n\n"
            return
        else:
            print('Login successful')
            yield "data: login successful\n\n"

        await asyncio.sleep(2)

        yield f"data: {response.text}\n\n"

        await asyncio.sleep(2)

        yield "data: end\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
