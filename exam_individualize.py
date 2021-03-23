#import gspread
#gc = gspread.oauth()
#sheet = gc.open_by_key('1AiiaEhz-8_4oWCQ0_4Z1mUCMK3C_kjyB0eyLO1ezHHE')

from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
import hashlib
from pathlib import Path
import pickle
import shutil
import urllib.parse

import general

#from pydrive2.auth import GoogleAuth
#from pydrive2.drive import GoogleDrive
#auth = GoogleAuth()
#drive = GoogleDrive(auth)
#x = drive.ListFile({'q': folder + ' in parents and trashed = false'}).GetList()

class Context:
    def load_creds(self):
        token_file = Path('token.pickle')

        self.creds = None
        if token_file.exists():
            with token_file.open('rb') as token:
                self.creds = pickle.load(token)

        if not self.creds or not self.creds.valid:
            if self.creds and self.creds.expired and self.creds.refresh_token:
                self.creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    'credentials.json',
                    [
                        'https://www.googleapis.com/auth/drive',
                        'https://www.googleapis.com/auth/documents',
                    ]
                )
                self.creds = flow.run_local_server(port = 0)

            with token_file.open('wb') as token:
                pickle.dump(self.creds, token)

    def __init__(self):
        self.load_creds()
        self.drive = build('drive', 'v3', credentials = self.creds, cache_discovery = False)
        self.docs = build('docs', 'v1', credentials = self.creds, cache_discovery = False)

    def get_parent(self, id):
        return self.drive.files().get(fileId = id, fields = 'parents').execute()['parents'][0]

    def list(self, id):
        r = self.drive.files().list(q = "'" + id + "' in parents and trashed = false").execute()
        assert not r['incompleteSearch']
        return [x['id'] for x in r['files']]

    def delete(self, id):
        self.drive.files().delete(fileId = id).execute()

    def move(self, id, target):
        self.drive.files().update(fileId = id, removeParents = self.get_parent(id), addParents = target).execute()

    def copy(self, id, name):
        return self.drive.files().copy(fileId = id, body = {'name': name}).execute()['id']

    def copy_to(self, id, name, target):
        id = self.copy(id, name)
        self.move(id, target)
        return id

    def save_as_pdf(self, id, path):
        data = self.drive.files().export(fileId = id, mimeType = 'application/pdf').execute()
        path.write_bytes(data)

    def save_as_docx(self, id, path):
        data = self.drive.files().export(fileId = id, mimeType = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document').execute()
        path.write_bytes(data)

    def save_as_odt(self, id, path):
        data = self.drive.files().export(fileId = id, mimeType = 'application/vnd.oasis.opendocument.text').execute()
        path.write_bytes(data)

    def batch_update(self, id, requests):
        self.docs.documents().batchUpdate(documentId = id, body = {'requests': requests}).execute()

    def replace(self, key, value):
        return {
            'replaceAllText': {
                'containsText': {
                    'text': '{{' + key + '}}',
                    'matchCase': 'true',
                },
                'replaceText': value,
            }
        }

    def replace_image(self, image_id, uri):
        return {
            'replaceImage': {
                'imageObjectId': image_id,
                'uri': uri,
            }
        }

c = Context()

exam = '1S7Nk6o-rFvi79nfCb2KRNkkvDBOdW55vcFAjj6qXfoA'
exam_solution = '1wS4FXVSM1YNUY3ahW7DRG5xnwg70ivwB7-DZGVmF3FI'

share_dir = Path('/home/noname/DIT181/exam/uxul')
share_url = 'http://uxul.org/~noname/exam/'

import graph
import priority_queue
import hash_table
import complexity
import sorting

def generate(integration_id, dir, solution = False):
    questions = [
        ('Q1', complexity.Question(integration_id)),
        ('Q2', sorting.QuestionQuicksort(integration_id)),
        ('Q2', sorting.QuestionMergeSort(integration_id)),
        ('Q4', priority_queue.Question(integration_id)),
        ('Q5', hash_table.Question(integration_id)),
        ('Q6', graph.QuestionDijkstra(integration_id)),
    ]

    id = c.copy(exam_solution if solution else exam, 'tmp')

    requests = []
    for prefix, question in questions:
        for key, value in question.replacement_sol() if solution else question.replacement():
            requests.append(c.replace(f'{prefix}:{key}', value))
        if hasattr(question, 'replacement_img'):
            for key, value in question.replacement_img():
                name = key + '_' + value.name
                shutil.copyfile(value, share_dir / name)
                requests.append(c.replace_image(key, share_url + urllib.parse.quote(name)))

    r = c.batch_update(id, requests)

    c.save_as_pdf(id, dir / 'test.pdf')
    #c.save_as_docx(id, dir / 'test.docx')
    #c.save_as_odt(id, dir / 'test.odt')

    c.delete(id)

for i in range(20):
    dir = Path('/home/noname/DIT181/exam/sol/{}'.format(i))
    general.mkdir_fresh(dir)
    generate(str(i), dir, solution = True)
