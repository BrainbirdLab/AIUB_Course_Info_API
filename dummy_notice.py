
# Dummy notices data

notices_items = [
    '05 Sep::Pre Registration Flowchart of Fall 24-25',
    '11 Sep::22nd Convocation List [Final Release]',
    '12 Sep::Data collection for Facial Access Control System',
    '13 Sep::AIUB Sports Fest 2024 Announcement',
    '14 Sep::Robotics Club Meeting',
    '15 Sep::AIUB Career Fair 2024',
    '17 Sep::Google I/O Extended 2024',
    '19 Sep::AIUB Hackathon 2024',
]

notices_data = [
    [
        notices_items[0],
        notices_items[1],
        notices_items[2]
    ],
    [
        notices_items[0],
        notices_items[1],
        notices_items[2],
    ],
    [
        notices_items[1],
        notices_items[2],
        notices_items[3],
    ],
    [
        notices_items[2],
        notices_items[3],
        notices_items[4],
    ],
    [
        notices_items[4],
        notices_items[5],
        notices_items[6],
    ],
    [
        notices_items[5],
        notices_items[6],
        notices_items[7],
    ]
]

# Async function to simulate fetching new notices'
count = 0
async def fetch_new_notice(_: int):
    global count
    
    if count == len(notices_data) - 1:
        count -= 1
    
    notice_list = notices_data[count]
    count += 1
    
    return notice_list
