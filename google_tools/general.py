import json
import logging
from pathlib import Path
import pickle
import shlex
import shutil
import urllib.parse

import google.auth.transport.requests
import google.oauth2.service_account
import google_auth_oauthlib.flow

import general
import path_tools

from .drive import Drive, TemporaryFile
from .documents import Documents


logger = logging.getLogger('google_tools.general')

this_dir = Path(__file__).parent

def scope_url(scope):
    return 'https://www.googleapis.com/auth/' + urllib.parse.quote(scope)

def load_secrets(path):
    ''' Decode a secrets file (in JSON format) into a Python object. '''
    with path.open() as file:
        return json.load(file)

def is_service_account(secrets):
    ''' Determined if the given secrets object is for a service account. '''
    return isinstance(secrets, dict) and secrets.get('type') == 'service_account'

def get_token_for_scopes(
    scopes,
    credentials = this_dir / 'credentials.json',
    cached_token = this_dir / 'token.pickle',
    prefix_url = True,
):
    '''
    Get an access token for the desired scopes.
    The function detects automatically if the credentials are client secrets for an app or a service account.
    The access token is optionally cached (if cached_token has a value) to avoid unnecessary authentication calls.
    This is only applicable to client secrets.
    The scopes should only be given as full URIs if prefix_url is False.
    '''
    if prefix_url:
        scopes = list(map(scope_url, scopes))

    creds = load_secrets(credentials)
    if is_service_account(creds):
        return google.oauth2.service_account.Credentials.from_service_account_info(
            info = creds,
            scopes = scopes,
        )

    token = None
    if cached_token and cached_token.exists():
        with cached_token.open('rb') as file:
            try:
                token = pickle.load(file)
            except Exception:
                logger.warning('Failed to load cached authentication token')

    if token and token.has_scopes(scopes):
        if token.expired and token.refresh_token:
            token.refresh(google.auth.transport.requests.Request())
        return token

    token = google_auth_oauthlib.flow.InstalledAppFlow.from_client_config(
        creds,
        scopes = scopes
    ).run_local_server(port = 0)
    if cached_token:
        with cached_token.open('wb') as file:
            pickle.dump(token, file)
    return token

def generate_from_template_document(
    output_paths,
    name,
    token,
    id,
    replacements = dict(),
    replacements_img = dict(),
    share_dir = None,
    share_url = None,
):
    '''
    Generate documents of various file types from the template document with given id.

    token is a Goolge OAuth2 token with scopes for drives and documents.

    output_paths is a map from file types to generated (specified by suffix) to output paths.

    replacements is a dictionary specifying textual replacements.

    replacements_img is a dictionary from image ids to paths to image files to use as replacement.
    The replacements will be scaled to the dimensions of the corresponding image in the template.
    share_dir and share_url are required if images are to be replaced.
    share_url is the url of a directory (with trailing slash) from which Google Docs will read an uploaded image.
    share_dir is the path to a local directory from which the files in share_url are populated.
    '''

    drive = Drive(token)
    docs = Documents(token)

    with TemporaryFile(drive, id, name) as id_copy:
        with path_tools.ScopedFiles() as files:
            # Collect all replacement requests.
            requests = []
            for key, value in replacements.items():
                requests.append(Documents.request_replace(key, value))
            for key, value in replacements_img.items():
                name = key + '_' + value.name
                share_file = share_dir / name

                # Copy and unlink instead of renaming because 'value' could be a symlink that might
                # have no meaning to the HTTP server that will serve the file request from Google Docs.
                shutil.copyfile(value, share_file)
                files.add(share_file)
                value.unlink()

                requests.append(Documents.request_replace_image(key, share_url + urllib.parse.quote(name)))

            # Perform the replacements as a single batch request.
            logger.log(logging.DEBUG, f'Performing replacements:\n{requests}\n...')
            if requests:
                docs.batch_update(id_copy, requests)

        # Export the document in the requested file types.
        for suffix, path in output_paths.items():
            logger.log(logging.DEBUG, f'Generating {shlex.quote(str(path))}...')
            drive.export(id_copy, path, Drive.mime_types_document[suffix])

def namespaced_replacements(sections):
    '''
    A namespaced way of generating the pair (replacements, replacements_img) for generate_from_template_document.
    Sections is an iterable of pairs of section prefixes (e.g. 'Q1') and objects with optional iterables
    * replacements
    * replacements_img
    of key-value pairs.
    In the case of replacements, a key KEY represents a textual occurrence of {{Q1:KEY}}.
    '''

    replacements = []
    replacements_img = []

    for prefix, section in sections:
        for key, value in getattr(section, 'replacements', []):
            replacements.append((f'{{{{{prefix}:{key}}}}}', value))
        for key, value in getattr(section, 'replacements_img', []):
            replacements_img.append((key, value))

    return (general.sdict(replacements), general.sdict(replacements_img))
