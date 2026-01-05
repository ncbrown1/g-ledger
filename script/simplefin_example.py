import base64
import requests

# 1. Get a Setup Token
setup_token = input('Setup Token? ')

# 2. Claim an Access URL
claim_url = base64.b64decode(setup_token.encode('ascii'))
response = requests.post(claim_url)
access_url = response.text

print(access_url)

# 3. Get some data
scheme, rest = access_url.split('//', 1)
auth, rest = rest.split('@', 1)
url = scheme + '//' + rest + '/accounts'
username, password = auth.split(':', 1)

response = requests.get(url, auth=(username, password))
data = response.json()

# do something interesting with the data
import datetime
def ts_to_datetime(ts):
    return datetime.datetime.fromtimestamp(ts)

for account in data['accounts']:
    account['balance-date'] = ts_to_datetime(account['balance-date'])
    print('\n{balance-date} {balance:>8} {name}'.format(**account))
    print('-'*60)
    for transaction in account['transactions']:
        transaction['posted'] = ts_to_datetime(transaction['posted'])
        print('{posted} {amount:>8} {description}'.format(**transaction))