import os
import logging
from fastapi import FastAPI, APIRouter, UploadFile, File, Form, HTTPException, Request, Response
from pydantic import BaseModel
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

# ==== Logger Setup ====
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("gpt_action_api")

# ==== FastAPI App ====
app = FastAPI(
    title="GPT Actions API",
    version="1.0.0",
    description="API for processing messages and files with user context for GPT Actions.",
    servers=[
        {
            "url": "https://mayoapi-cfa5b9gbazh2dgau.centralus-01.azurewebsites.net",  # 🔁 Replace with your real API URL
            "description": "Production Server"
        }
    ]
)

# ==== Middleware for Logging ====
class LoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        body = await request.body()
        logger.info(f"Incoming request: {request.method} {request.url} Body: {body.decode('utf-8', errors='ignore')}")
        try:
            response = await call_next(request)
        except Exception as e:
            logger.exception("Unhandled exception during request processing")
            raise
        if isinstance(response, Response):
            logger.info(f"Response status: {response.status_code}")
        return response

app.add_middleware(LoggingMiddleware)

# ==== Schemas ====
class UserMessage(BaseModel):
    userId: str
    username: str
    message: str

class MessageResponse(BaseModel):
    userId: str
    username: str
    message: str
    response: str

class FileUploadResponse(BaseModel):
    filename: str
    status: str

class MessageWithFileResponse(BaseModel):
    messageResponse: MessageResponse
    fileUpload: FileUploadResponse

class HealthStatus(BaseModel):
    status: str

class ErrorResponse(BaseModel):
    detail: str

# ==== Services ====
def handle_user_message(msg: UserMessage) -> dict:
    if not msg.message.strip():
        raise HTTPException(status_code=500, detail="Message cannot be empty.")
    response = {
        "userId": msg.userId,
        "username": msg.username,
        "message": msg.message,
        "response": f"Echo to {msg.username}: {msg.message}"
    }
    logger.info(f"Message handler output: {response}")
    return response

def save_document(file: UploadFile) -> dict:
    try:
        UPLOAD_DIR = "uploaded_documents"
        os.makedirs(UPLOAD_DIR, exist_ok=True)
        file_path = os.path.join(UPLOAD_DIR, file.filename)
        with open(file_path, "wb") as f:
            f.write(file.file.read())
        result = {"filename": file.filename, "status": "uploaded"}
        logger.info(f"File saved: {result}")
        return result
    except Exception as e:
        logger.exception("File upload failed")
        raise HTTPException(status_code=500, detail=str(e))

# ==== Routers ====
message_router = APIRouter()
document_router = APIRouter()

@message_router.post(
    "",
    response_model=MessageResponse,
    responses={500: {"model": ErrorResponse}},
    openapi_extra={"operationId": "sendMessage"}
)
async def process_message(msg: UserMessage):
    return handle_user_message(msg)

@message_router.post(
    "/with-file",
    response_model=MessageWithFileResponse,
    responses={500: {"model": ErrorResponse}},
    openapi_extra={"operationId": "sendMessageWithFile"}
)
async def process_message_with_file(
    userId: str = Form(...),
    username: str = Form(...),
    message: str = Form(...),
    file: UploadFile = File(...)
):
    file_result = save_document(file)
    msg = UserMessage(userId=userId, username=username, message=message)
    message_result = handle_user_message(msg)
    result = {
        "messageResponse": message_result,
        "fileUpload": file_result
    }
    logger.info(f"Combined message and file response: {result}")
    return result

@document_router.post(
    "/upload",
    response_model=FileUploadResponse,
    responses={500: {"model": ErrorResponse}},
    openapi_extra={"operationId": "uploadUserFile"}
)
async def upload_document(
    userId: str = Form(...),
    username: str = Form(...),
    file: UploadFile = File(...)
):
    return save_document(file)

@app.get(
    "/health",
    response_model=HealthStatus,
    responses={500: {"model": ErrorResponse}},
    openapi_extra={"operationId": "checkHealth"}
)
async def health_check():
    logger.info("Health check OK")
    print("HEALTH API invoked.")
    return {"status": "ok"}

# ==== Register Routers ====
app.include_router(message_router, prefix="/message", tags=["Messages"])
app.include_router(document_router, prefix="/document", tags=["Documents"])

# if __name__ == "__main__":
#     import uvicorn
#     uvicorn.run(app, host="0.0.0.0", port=8000)
