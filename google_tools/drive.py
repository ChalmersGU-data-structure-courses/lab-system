import logging

import googleapiclient.discovery


logger = logging.getLogger(__name__)


class Drive:
    default_scopes = ["drive"]

    def __init__(self, token):
        self.drive = googleapiclient.discovery.build(
            "drive", "v3", credentials=token, cache_discovery=False
        )

    def get_parent(self, id):
        return (
            self.drive.files().get(fileId=id, fields="parents").execute()["parents"][0]
        )

    def list(self, id):
        r = (
            self.drive.files()
            .list(q="'" + id + "' in parents and trashed = false")
            .execute()
        )
        assert not r["incompleteSearch"]
        return [x["id"] for x in r["files"]]

    def delete(self, id):
        self.drive.files().delete(fileId=id).execute()

    def move(self, id, target):
        self.drive.files().update(
            fileId=id, removeParents=self.get_parent(id), addParents=target
        ).execute()

    def copy(self, id, name):
        return self.drive.files().copy(fileId=id, body={"name": name}).execute()["id"]

    def copy_to(self, id, name, target):
        id = self.copy(id, name)
        self.move(id, target)
        return id

    mime_types_document = {
        "pdf": "application/pdf",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "odt": "application/vnd.oasis.opendocument.text",
    }

    def export(self, id, path, mime_type):
        data = self.drive.files().export(fileId=id, mimeType=mime_type).execute()
        path.write_bytes(data)


class TemporaryFile:
    def __init__(self, drive, id, name):
        self.drive = drive
        self.id = id
        self.name = name

    def __enter__(self):
        logger.log(logging.DEBUG, f"Creating a copy of drive file {self.id}...")
        self.id_copy = self.drive.copy(self.id, self.name)
        return self.id_copy

    def __exit__(self, type, value, traceback):
        logger.log(logging.DEBUG, "Deleting copy of drive file...")
        self.drive.delete(self.id_copy)
