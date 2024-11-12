from fastapi import FastAPI

app = FastAPI()

def todo():
    pass

'''
 Eventually, this will
 1. Listen for incoming POST requests from GitHub
 2. On merge to main branch, pull the latest changes
 3. Restart all docker containers
    docker-compose down
    docker-compose up -d --build
'''
