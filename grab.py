

courses = {
    "MIS4012": {
        "course_name": "E-COMMERCE, E-GOVERNANCE & E-SERIES",
        "credit": 3,
        "prerequisites": [
            "CSC3215"
        ]
    },
    "EEE3103": {
        "course_name": "DIGITAL SIGNAL PROCESSING",
        "credit": 3,
        "prerequisites": [
            "EEE2213"
        ]
    },
    "EEE4217": {
        "course_name": "VLSI CIRCUIT DESIGN",
        "credit": 3,
        "prerequisites": [
            "EEE4241",
            "EEE4242"
        ]
    }
}

completed = {
    "EEE3102": {
        "grade": "A"
    },
    "EEE2213": {
        "grade": "A"
    },
    "EEE4241": {
        "grade": "A"
    },
}

print("EEE4241" in completed)

#if all of EEE4217 prerequisites meets the completed courses