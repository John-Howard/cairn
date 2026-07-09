from fastapi import FastAPI

import cairn

app = FastAPI()


@app.get("/healthz")
def healthz():
    return {"status": "ok", "version": cairn.__version__}
