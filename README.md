# API Server for AIUB course info
This server gathers information like Semesters, Class times and courses information and sends back to the client. 
This need your username and password as we cannot simply get this information from your university portal.
This server then logs into your portal using those username and password and then cooks the data and forwards to the client app.

## How we work

1. **User Authentication**  
    The client sends a username and password to the API. These credentials are securely transmitted and used to authenticate the user against the university portal.

2. **Data Retrieval**  
    Once authenticated, the server logs into the university portal on behalf of the user to gather detailed information including semesters, class schedules, and course data.

3. **Data Processing and Formatting**  
    The retrieved data is cleaned, formatted, and structured to ensure it meets the client application's requirements. This may include filtering, sorting, and organizing the information.

4. **Response Delivery**  
    After processing, the server sends the formatted data back to the client application, ensuring that the client receives updated and structured information in a secure manner.

5. **Error Handling & Logging**  
    Throughout the process, any issues or errors are logged for troubleshooting and improvement, ensuring high availability and reliability of the service.

6. **Event-Driven Architecture**  
    The server is designed to be event-driven, allowing it to handle multiple requests concurrently and efficiently. This ensures that the server can scale to meet the demands of multiple users and provide a responsive and reliable service.

7. **SSE (Server-Sent Events)**  
    The server uses Server-Sent Events (SSE) to push real-time updates and notifications to the client application. This ensures that the client receives timely and relevant information without the need for constant polling or manual refreshes.

Client: https://aiub.brainbird.org
