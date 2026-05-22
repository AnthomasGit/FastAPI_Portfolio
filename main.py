from enum import Enum

from fastapi import FastAPI

class ModelName(str, Enum):
    imagegen = "imagegen"
app = FastAPI()


@app.get("/")
async def root():
    return {"message": "Hello World"}


@app.get("/hello/{name}")
async def say_hello(name: str):
    return {"message": f"Hello {name}"}

@app.get("/portfolio")
async def display_workflow():
    return ##Return apps/workflows##

@app.get("/portfolio/{model_name}")
async def boot_service(model_name: ModelName):
    if model_name is ModelName.imagegen:
        return ##Image Generator##

##@app.get("/portfolio/{model_name}/{query}")
##async def generate_pic(query: str):
    return