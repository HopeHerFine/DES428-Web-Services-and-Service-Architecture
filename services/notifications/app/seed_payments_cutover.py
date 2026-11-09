"""Create synthetic legacy financial history through the real inherited UI APIs."""
import json
import os
import random
from datetime import date,timedelta
from .smoke_gateway import browser_login,request


def main():
    if os.environ.get('CUTOVER_FIXTURE')!='synthetic':raise RuntimeError('Synthetic rehearsal only')
    customer=browser_login('nong@example.com')
    provider=browser_login('sparkle@example.com')
    service=request(customer,'/api/services/2')
    addresses=request(customer,'/api/customer/addresses')
    def book(method):
        for offset in random.sample(range(30,180),15):
            day=(date.today()+timedelta(days=offset)).isoformat()
            slots=request(customer,f"/api/providers/1/slots?date={day}&duration={service['duration_min']}")['slots']
            if slots:
                return request(customer,'/api/bookings',{'provider_id':1,'address_id':addresses[0]['id'],
                    'service_date':day,'starting_time':slots[0],'items':[{'service_id':2,'quantity':1}],'payment_method':method})
        raise RuntimeError('No fixture booking slot')
    paid=book('gateway')
    request(customer,'/api/payments/simulate',{'order_id':paid['order']['id']})
    for method in ('gateway','cod'):
        placed=paid if method=='gateway' else book('cod')
        order=placed['order']['id']
        request(provider,f'/api/bookings/{order}/confirm',{})
        request(provider,f'/api/bookings/{order}/start',{})
        request(provider,f'/api/bookings/{order}/complete',{'otp':placed['otp']})
    book('gateway') # Includes an unpaid legacy intent in the migration.
    wallet=request(provider,'/api/provider/wallet')
    assert wallet['balance_cents']>0 and wallet['commission_owed_cents']>0
    print(json.dumps({'result':'PASS','fixture':'synthetic-legacy-payments','bookings':3,'legacy_wallet_nonzero':True}))


if __name__=='__main__':main()
