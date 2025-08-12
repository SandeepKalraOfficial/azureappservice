import os
import logging
import json
import base64
from fastapi import FastAPI, APIRouter, UploadFile, File, Form, HTTPException, Request, Response, Depends
from pydantic import BaseModel
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

# ==== Logger Setup ====
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger("gpt_action_api")

# ==== FastAPI App ====
app = FastAPI(
    title="GPT Actions API",
    version="1.0.0",
    description="API for processing messages and files with user context for GPT Actions.",
    servers=[
        {
            "url": "https://mayoapi-cfa5b9gbazh2dgau.centralus-01.azurewebsites.net",
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

# ==== User Extraction from Azure AD Headers ====
async def get_user_from_request(request: Request) -> dict:
    principal_encoded = request.headers.get("X-MS-CLIENT-PRINCIPAL")
    if principal_encoded:
        try:
            principal_decoded = base64.b64decode(principal_encoded).decode("utf-8")
            principal_json = json.loads(principal_decoded)
            claims = {claim["typ"]: claim["val"] for claim in principal_json.get("claims", [])}
            return claims
        except Exception as e:
            logger.warning(f"Failed to decode user principal: {e}")
            return {}
    return {}

# ==== Schemas ====
class UserMessage(BaseModel):
    userId: str
    username: str
    message: str

class UserMessageWithBase64(BaseModel):
    userId: str
    username: str
    message: str
    filename: str
    fileData: str

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
    "/with-messangeAndbase64File",
    response_model=MessageWithFileResponse,
    responses={500: {"model": ErrorResponse}},
    openapi_extra={"operationId": "sendMessageWithBase64"}
)
async def process_message_with_base64_file(msg: UserMessageWithBase64):
    try:
        UPLOAD_DIR = "uploaded_documents"
        os.makedirs(UPLOAD_DIR, exist_ok=True)
        file_path = os.path.join(UPLOAD_DIR, msg.filename)
        with open(file_path, "wb") as f:
            f.write(base64.b64decode(msg.fileData))
        file_result = {"filename": msg.filename, "status": "uploaded"}
        message_result = handle_user_message(UserMessage(
            userId=msg.userId,
            username=msg.username,
            message=msg.message
        ))
        result = {
            "messageResponse": message_result,
            "fileUpload": file_result
        }
        logger.info(f"Base64 file and message processed: {result}")
        return result
    except Exception as e:
        logger.exception("Base64 file processing failed")
        raise HTTPException(status_code=500, detail=str(e))

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

# ==== Health Check with User Info ====
@app.get(
    "/health",
    response_model=HealthStatus,
    responses={500: {"model": ErrorResponse}},
    openapi_extra={"operationId": "checkHealth"}
)
async def health_check(request: Request):
    user_claims = await get_user_from_request(request)
    email = user_claims.get("http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress", "unknown")
    logger.info(f"Health check invoked by user: {email}")
    return {"status": f"ok - user: {email}"}

# ==== Register Routers ====
app.include_router(message_router, prefix="/message", tags=["Messages"])
app.include_router(document_router, prefix="/document", tags=["Documents"])
