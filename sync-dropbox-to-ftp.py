#!/usr/bin/env python3

"""The initial options file should look like:

{
  "state": { "cursor": null, "left": [] },
  "options": {
    "ftp": {
      "auth": { "host": "FTP_HOST", "user": "FTP_USER", "passwd": "FTP_PASSWORD" },
      "path": "FTP_DIRECTORY_NAME"
    },
    "dropbox": {
      "auth": { "access_token": "ACCESS_TOKEN" },
      "path": "DROPBOX_DIRECTORY_NAME"
    }
  }
}
"""

import argparse
import contextlib
import ftplib
import json
import os.path
import sys
import urllib.parse
import urllib.request


class Dropbox:
  def __init__(self, access_token):
    self._access_token = access_token

  def _urlopen(self, url, data=None, headers={}):
    headers['Authorization'] = 'Bearer ' + self._access_token
    if data is not None:
      data = urllib.parse.urlencode(data).encode()
    request = urllib.request.Request(url=url, data=data, headers=headers)
    return urllib.request.urlopen(request, cadefault=True)

  def get_added_files(self, path, cursor):
    # http.client.HTTPConnection.debuglevel = 1
    data = {'path_prefix': path}
    deltas = {'has_more': True}
    while deltas['has_more']:
      if cursor:
        data['cursor'] = cursor
      deltas = json.loads(
        self._urlopen(url='https://api.dropbox.com/1/delta', data=data)
        .read().decode())
      added_files = [entry[0] for entry in deltas['entries'] if entry[1] and not entry[1]['is_dir']]
      cursor = deltas['cursor']
    return added_files, cursor

  def get_file(self, path):
    return self._urlopen('https://api-content.dropbox.com/1/files/auto/' + path)


@contextlib.contextmanager
def Ftp(host, user, passwd):
  with ftplib.FTP(host=host) as ftp:
    ftp.login(user=user, passwd=passwd)

    class Actions:
      def __init__(self, ftp):
        self._ftp = ftp

      def upload(self, path, f, callback=lambda num_bytes: None):
        num_bytes = [0]
        def cb(buff):
          num_bytes[0] += len(buff)
          callback(num_bytes[0])
        self._ftp.storbinary('STOR ' + os.path.join(self._ftp.pwd(), path), f, blocksize=1024*1024, callback=cb)
        
    yield Actions(ftp)


if __name__ == '__main__':
  parser = argparse.ArgumentParser()
  parser.add_argument("--conf", default="~/.sync-dropbox-to-ftp.conf")
  parser.add_argument("--noupdate", action="store_true", default=False,
                      help="Do not update the configuration file.")
  args = parser.parse_args()
  conf_file = os.path.expanduser(args.conf)
  with open(conf_file) as f:
    conf = json.load(f)
  options = conf['options']
  state = conf['state']

  db = Dropbox(**options['dropbox']['auth'])
  left, state['left'] = state['left'], []
  if not left:
    left, state['cursor'] = db.get_added_files(options['dropbox']['path'], state['cursor'])

  with Ftp(**options['ftp']['auth']) as ftp:
    for path in left:
      try:
        def display(num_bytes):
          print('{}: Uploaded {} bytes...'.format(path, num_bytes), end='\r', file=sys.stderr, flush=True)
        display(0)

        ftp.upload(os.path.join(options['ftp']['path'], os.path.basename(path)),
                   db.get_file(path),
                   callback=display)
      except Exception as e:
        print('\n{}: Failed with {}'.format(path, e), file=sys.stderr, flush=True)
        state['left'].append(path)
      else:
        print('\n{}: Done'.format(path), file=sys.stderr, flush=True)
        print(path, flush=True)

  if not args.noupdate:
    with open(conf_file, 'w') as f:
      json.dump(conf, f, indent=2)
