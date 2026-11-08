"""Small authenticated read/write workload for the laptop memory rehearsal."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import socket
import time
from urllib.request import Request
from uuid import uuid4
from .smoke_gateway import browser_login, ORIGIN


def blocked_egress():
    for address in [('1.1.1.1',443),('8.8.8.8',53)]:
        try:
            connection=socket.create_connection(address,timeout=2)
        except OSError:
            continue
        connection.close()
        raise RuntimeError('Offline test unexpectedly has outbound connectivity')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--seconds',type=int,default=60)
    parser.add_argument('--report')
    args=parser.parse_args()
    if not 10 <= args.seconds <= 180:
        raise ValueError('Workload duration must be 10..180 seconds')
    blocked_egress()
    clients=[browser_login('sparkle@example.com') for _ in range(2)]
    def exercise(client):
        count=0
        writes=0
        key='offline-'+uuid4().hex
        deadline=time.monotonic()+args.seconds
        while time.monotonic()<deadline:
            with client.open(ORIGIN+'/api/notifications',timeout=30) as response:
                rows=json.load(response)
                assert response.status==200
            count+=1
            if rows:
                request=Request(ORIGIN+f"/api/notifications/{rows[0]['id']}/read",data=b'',
                    headers={'Origin':ORIGIN,'Idempotency-Key':key},method='POST')
                with client.open(request,timeout=30) as response:
                    assert response.status==200 and json.load(response)['read_at']
                count+=1
                writes+=1
            if count % 8 == 0:
                with client.open(ORIGIN+'/notifications',timeout=30) as response:
                    assert response.status==200 and 'temporarily unavailable' not in response.read().decode()
                count+=1
            time.sleep(0.2)
        assert writes > 0, 'Workload did not exercise any authenticated writes'
        return count, writes
    with ThreadPoolExecutor(max_workers=2) as pool:
        counts=list(pool.map(exercise,clients))
    result={'result':'PASS','probe':'offline-workload','clients':2,
        'duration_seconds':args.seconds,'successful_requests':sum(row[0] for row in counts),
        'successful_read_updates':sum(row[1] for row in counts),'outbound_connections_blocked':True}
    if args.report:
        with Path(args.report).open('x',encoding='utf-8') as report:
            json.dump(result,report)
    print(json.dumps(result))


if __name__=='__main__':
    main()
