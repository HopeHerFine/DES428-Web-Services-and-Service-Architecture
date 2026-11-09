"""Read-only checks through an unpublished gateway before public release."""
import json
import argparse
from pathlib import Path
from urllib.error import HTTPError
from .smoke_gateway import browser_login, request, ORIGIN


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--legacy',action='store_true')
    args=parser.parse_args()
    state=json.loads(Path('/migration/source/status.json').read_text())
    assert state['phase']==('rolled_back' if args.legacy else 'activated')
    document=json.loads(Path('/migration/source',state['run_id'],'history.json').read_text())
    provider=browser_login('sparkle@example.com')
    expected=next(row for row in document['wallets'] if row['provider_id']==1)
    wallet=request(provider,'/api/provider/wallet')
    assert wallet['balance_cents']==expected['balance_cents']
    assert wallet['commission_owed_cents']==expected['commission_owed_cents']
    expected_ids={row['id'] for row in document['transactions'] if row['provider_id']==1}
    assert {row['id'] for row in wallet['transactions']}==expected_ids
    with provider.open(ORIGIN+'/provider/wallet',timeout=30) as response:
        assert 'Wallet' in response.read().decode()
    try:request(provider,'/api/provider/wallet',token='forged.invalid.token')
    except HTTPError as error:assert error.code==401
    else:raise AssertionError('Forged payment token accepted')
    print(json.dumps({'result':'PASS','probe':'payments-cutover-readonly','snapshot_sha256':state['snapshot_sha256'],
        'remote_wallet_matches':True,'financial_writes':0,'public_port_opened':args.legacy}))


if __name__=='__main__':main()
