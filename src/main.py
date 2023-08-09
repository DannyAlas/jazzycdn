import logging
import os
import sys

import axiom
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.exceptions import HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from firebase_admin import credentials, initialize_app
from google.cloud import firestore
from minio import Minio

from .logging import AxiomHandler

load_dotenv()

################################### LOGGING ###################################
logging.basicConfig(
    level=logging.DEBUG, format="%(asctime)s - %(levelname)s: %(message)s"
)
log = logging.getLogger(__name__)


axiom_token = os.getenv("AXIOM_API_TOKEN")
ax_client = axiom.Client(
    token=os.getenv("AXIOM_API_TOKEN"), org_id=os.getenv("AXIOM_ORG_ID")
)
axiom_handler = AxiomHandler(ax_client, "logs", level=logging.DEBUG, interval=1)
log.addHandler(axiom_handler)


def exception_handler(exeption_type, exception, traceback):
    # set the message to me the last lines of the traceback
    log.error(
        f"Uncaught exception: {exception}",
        exc_info=(exeption_type, exception, traceback),
    )


sys.excepthook = exception_handler

################################## APP INITS ##################################
MinioClient = Minio(
    "s3.danielalas.com",
    access_key=os.getenv("MINIO_ACCESS_KEY"),
    secret_key=os.getenv("MINIO_SECRET_KEY"),
)
bucket = "public"
object_prefix = "host/"

env_creds = {
    "type": os.getenv("TYPE"),
    "project_id": os.getenv("PROJECT_ID"),
    "private_key_id": os.getenv("PRIVATE_KEY_ID"),
    "private_key": os.getenv("PRIVATE_KEY").replace("\\n", "\n"),
    "client_email": os.getenv("CLIENT_EMAIL"),
    "client_id": os.getenv("CLIENT_ID"),
    "auth_uri": os.getenv("AUTH_URI"),
    "token_uri": os.getenv("TOKEN_URI"),
    "auth_provider_x509_cert_url": os.getenv("AUTH_PROVIDER_X509_CERT_URL"),
    "client_x509_cert_url": os.getenv("CLIENT_X509_CERT_URL"),
}
cred = credentials.Certificate(env_creds)
firebase = initialize_app(cred)
db = firestore.Client.from_service_account_info(env_creds)

app = FastAPI()
allow_all = ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_all,
    allow_credentials=True,
    allow_methods=allow_all,
    allow_headers=allow_all,
)
app.mount("/public", StaticFiles(directory="./src/public"), name="public")

###############################################################################


def update_file_lastseen(file_name):
    try:
        db_file = db.collection("files").document(file_name).get().to_dict()
        if db_file.get("last_seen") is None:
            db_file["last_seen"] = firestore.SERVER_TIMESTAMP
        if db_file.get("views") is None:
            db_file["views"] = 0
        db_file["views"] += 1
        db.collection("files").document(file_name).set(db_file)
    except Exception as e:
        log.error(f"Error updating file last seen and views\n{e}")
        return HTTPException(status_code=500, detail=f"File Not Found In Database\n{e}")


@app.get("/{file_name}")
async def get_file(file_name: str):
    for file in MinioClient.list_objects(bucket, prefix=object_prefix):
        if str(file.object_name).strip(object_prefix) == file_name:
            update_file_lastseen(file_name)
            return StreamingResponse(
                MinioClient.get_object(bucket, file.object_name),
                media_type=file.content_type,
            )
    raise HTTPException(status_code=404, detail="File not found")
