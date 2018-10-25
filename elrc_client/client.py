import atexit
import json
import sys
import zipfile

import os
import requests
from elrc_client.settings import LOGIN_URL, API_ENDPOINT, LOGOUT_URL, API_OPERATIONS
from elrc_client.settings import logging
from elrc_client.utils.data_merger import get_update_with_ids
from elrc_client.utils.xml import parser


def to_dict(input_ordered_dict):
    return json.loads(json.dumps(input_ordered_dict, ensure_ascii=False))


class ELRCShareClient:
    def __init__(self):
        self.session = None
        self.csrftoken = None
        self.user_log_in = None
        self.logged_in = False
        self.headers = {
            'Content-Type': 'application/json'
        }
        if os.name == 'posix':
            self.download_dir = '/home/{}/ELRC-Downloads'.format(os.getlogin())
        elif os.name == 'nt':
            self.download_dir = 'C:/Users/{}/Downloads/ELRC-Downloads'.format(os.getlogin())
        atexit.register(self.logout)

    def login(self, username, password):
        try:
            self.session = requests.session()
            self.user_log_in = self.session.get(LOGIN_URL)
            self.csrftoken = self.session.cookies['csrftoken']
            if self.user_log_in.ok:
                login_data = {
                    'username': username,
                    'password': password,
                    'csrfmiddlewaretoken': self.csrftoken
                }
                # Login to site
                try:
                    login = self.session.post(LOGIN_URL, data=login_data)
                    if 'Your username and password didn\'t match' in login.text:
                        logging.error('Unsuccessful Login...')
                    else:
                        self.logged_in = True
                        logging.info('Login Successful!')
                except requests.exceptions.ConnectionError:
                    logging.error('Could not connect to remote host.')
        except requests.exceptions.ConnectionError:
            logging.error('Could not connect to remote host.')

    def logout(self):
        """
        Logout user and close session when program exits
        """
        if self.logged_in:
            try:
                self.session.get(LOGOUT_URL)
                self.session.close()
                self.logged_in = False
                logging.info("Logout....")
            except requests.exceptions.ConnectionError:
                logging.error('Could not connect to remote host.')
        else:
            pass

    def get_resource(self, rid=None, as_json=False, pretty=False):
        """
        Given an ELRC-SHARE Language Resource id, return the resource's metadata
        in a python dictionary.

        :param rid: ELRC Resource ID
        :param as_json: Boolean value. If False, the method returns a dictionary, else a json string
        :return: Python dictionary or json containing resource metadata
        """
        url = "{}{}".format(API_ENDPOINT, rid)
        indent = 4 if pretty else None
        try:
            request = self.session.get(url)
            if request.status_code == 401:
                return '401 Unauthorized Request'
            elif request.status_code == 400:
                return '400 Bad Request'
            elif request.status_code == 404:
                return 'Resource with rid {} was not found'.format(rid)
            if as_json:
                return json.dumps(json.loads(request.content), ensure_ascii=False, indent=indent)
            else:
                return json.loads(request.content)
        except requests.exceptions.ConnectionError:
            logging.error('Could not connect to remote host.')

    def get_my_resources(self, as_json=False):
        """
        Given an ELRC-SHARE Language Resource id, return the resource's metadata
        in a python dictionary.

        :param id: ELRC Resource ID
        :param as_json: Boolean value. If False, the method returns a dictionary, else a json string
        :return: Python dictionary or json containing resource metadata
        """
        try:
            request = self.session.get(API_ENDPOINT + '?limit=0')
            if request.status_code == 401:
                return '401 Unauthorized Request'
            elif request.status_code == 400:
                return '400 Bad Request'
            elif request.status_code == 404:
                return 'Resource with id {} was not found'.format(id)
            if as_json:
                return json.dumps(json.loads(request.content), ensure_ascii=False)
            else:
                return json.loads(request.content)
        except requests.exceptions.ConnectionError:
            logging.error('Could not connect to remote host.')

    def update_resource(self, id, xml_file=None):
        """
        Given an ELRC-SHARE Language Resource id, update the corresponding resource.

        :param id: ELRC Resource ID for the resource to be updated
        :param data: A python dictionary containing the data to be passed for updating the resource
        :return: status code (expected 202)
        """
        url = "{}{}".format(API_ENDPOINT, id)
        # populate
        data = parser.parse(open(os.path.join(os.path.dirname(__file__), xml_file), encoding='utf-8').read())
        final = get_update_with_ids(self.get_resource(id), to_dict(data))
        # final = to_dict(data)
        final['resourceInfo']['id'] = id
        try:
            request = self.session.patch(url, headers=self.headers,
                                         data=json.dumps(final, ensure_ascii=False).encode('utf-8'))
            print(request.status_code, request.content)
            return request.status_code, request.content
        except requests.exceptions.ConnectionError:
            logging.error('Could not connect to remote host.')

    def create_resource(self, description, dataset=None):
        resource_name = description.get('resourceInfo').get('identificationInfo').get('resourceName').get('en')
        try:
            request = self.session.post(API_ENDPOINT, headers=self.headers,
                                        data=json.dumps(description, ensure_ascii=False).encode('utf-8'))
            if request.status_code == 201:
                print("Metadata created".format(resource_name))
                new_id = json.loads(request.content).get('ID')
                try:
                    self.upload_data(new_id, dataset)
                except Exception as e:
                    logging.error(e)
                print("Resource '{}' has been created\n".format(resource_name))
                return
            elif request.status_code == 401:
                logging.error('401 Unauthorized Request')
                return
        except requests.exceptions.ConnectionError:
            logging.error('Could not connect to remote host.')

    def upload_data(self, resource_id, data_file):

        if not zipfile.is_zipfile(data_file):
            logging.error('Not a valid zip archive')
            return
        else:
            try:
                del self.headers['Content-Type']
            except KeyError:
                pass
            self.headers.update({'X-CSRFToken': self.session.cookies['csrftoken']})
            url = "{}upload_data/{}/".format(API_OPERATIONS, resource_id)

            files = {'resource': open(data_file, 'rb')}
            data = {
                'csrfmiddlewaretoken': self.session.cookies['csrftoken'],
                'uploadTerms': 'on',
                'api': True}

            print('Attempting dataset upload...')
            response = self.session.post(
                url,
                headers=self.headers,
                files=files,
                data=data
            )
            print(response.text)

    def create_resources(self, file, dataset=None):
        if zipfile.is_zipfile(file):
            zip_file = zipfile.ZipFile(file)
            for f in zip_file.namelist():
                logging.info('Processing file: {}'.format(f))
                data = parser.parse(zip_file.open(f).read())
                self.create_resource(data)
        else:
            logging.info('Processing file: {}'.format(file))
            data = parser.parse(open(os.path.join(os.path.dirname(__file__), file), encoding='utf-8').read())
            self.create_resource(data, dataset=dataset)

    def download_data(self, resource_id, destination='', progress=True):
        if self.logged_in:
            if not destination:
                destination = self.download_dir
            try:
                url = "{}get_data/{}/".format(API_OPERATIONS, resource_id)
                head = self.session.head(url)
                try:
                    print(head.headers.get('Content-Type'), head.status_code)
                    if head.headers.get('Content-Type') != 'application/zip':
                        if head.status_code == 200:
                            # returns a page with the message "No Download Available"
                            logging.error('Dataset for resource {} was not found'.format(resource_id))
                            return None
                        if head.status_code == 401:
                            logging.error('401 Unauthorized Request')
                            return None
                        elif head.status_code == 400:
                            logging.error('400 Bad Request')
                            return None
                        elif head.status_code == 404:
                            logging.error('Dataset for resource {} was not found'.format(resource_id))
                            return None
                        elif head.status_code == 500:
                            logging.error('Resource with id {} was not found'.format(resource_id))
                            return None
                        elif head.status_code == 403:
                            logging.error('Forbidden operation on resource with id {}.'.format(resource_id))
                            return None
                        elif 'No Download Available' in head.text:
                            logging.error('No download available for resource with id {}.'.format(resource_id))
                            return None
                    else:
                        logging.info('Downloading resource with id {}'.format(resource_id))
                        self._provide_download(url, resource_id, destination, progress=progress)
                except RuntimeError:
                    pass
                logging.info("Download complete.".format(resource_id))
                return "OK"
            except requests.exceptions.ConnectionError:
                logging.error('Could not connect to remote host.')
        else:
            logging.error("Please login to ELRC-SHARE using your credentials")

    def _provide_download(self, url, resource_id, destination, progress):
        # Check if destination directory is provided an whether it exists. If not create it
        if destination:
            os.makedirs(destination, exist_ok=True)
        with open(os.path.join(destination, "archive-{}.zip".format(resource_id)), 'wb') as f:
            response = self.session.get(url, stream=True)
            total = response.headers.get('content-length')

            if total is None:
                f.write(response.content)
            else:
                downloaded = 0
                total = int(total)
                for data in response.iter_content(chunk_size=max(int(total / 1000), 1024 * 1024)):
                    downloaded += len(data)
                    f.write(data)
                    done = int(50 * downloaded / total)
                    if progress:
                        sys.stdout.write('\r[{}{}]'.format('█' * done, '.' * (50 - done)))
                        sys.stdout.flush()
        if progress:
            sys.stdout.write('\n')
        return response