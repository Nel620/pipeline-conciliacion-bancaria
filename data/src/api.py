from fastapi import FastAPI
from pydantic import BaseModel
from main import correr_pipeline_financiero

app = FastAPI()

class RequestProcesar(BaseModel):
    file_path: str


@app.get("/")
def health():
    return {"estado": "Python Worker activo"}


@app.post("/procesar")
def procesar(data: RequestProcesar):
    output_dir = correr_pipeline_financiero(data.file_path)

    return {
        "estado": "OK",
        "output_dir": output_dir
    }




