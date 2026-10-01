import copy
import unittest
from rotation.planner import plan, validate
from flask import Flask
from rotation import rotation_api
app = Flask(__name__)
app.register_blueprint(rotation_api)

def fixture(h=6):
    ps=[dict(id=i,name=str(i),stock=200,growth=0,reserve=20,rest=2,max_stay=3,occupied_days=3 if i==1 else 0,rested_days=0 if i==1 else 20,available=[True]*h) for i in [1,2,3]]
    us=[dict(id='g',group='g',name='Grupo',animals=[1,2],origin=1,demand=10,allowed=[[True]*h for _ in ps],fixed=False,incompatible=[])]
    return dict(start='2026-10-01',horizon=h,paddocks=ps,units=us,time_limit=1)

class RotationTests(unittest.TestCase):
    def test_leave_maximum_and_keep_group(self):
        d=fixture();r=plan(d)
        self.assertIn(r['status'],['OPTIMO','FACTIBLE'])
        self.assertNotEqual(r['assignment']['g'][0],1)
        self.assertEqual(r['steps'][0]['animals'],[1,2])
        self.assertTrue(all(x['stock']>=x['reserve'] for x in r['projection'] if x['animals']))
    def test_excluded_never_used(self):
        d=fixture();d['paddocks'][1]['available']=[False]*6
        r=plan(d);self.assertNotIn(2,r['assignment']['g'])
    def test_all_excluded_infeasible(self):
        d=fixture()
        for p in d['paddocks']:p['available']=[False]*6
        self.assertEqual(plan(d)['status'],'INVIABLE')
    def test_insufficient_feed(self):
        d=fixture()
        for p in d['paddocks']:p['stock']=20
        self.assertEqual(plan(d)['status'],'INVIABLE')
    def test_rest_prevents_early_entry(self):
        d=fixture();d['paddocks'][1]['rested_days']=0;d['paddocks'][2]['rested_days']=0
        self.assertEqual(plan(d)['status'],'INVIABLE')
    def test_fixed_animals_still_consume(self):
        d=fixture();d['units'][0]['fixed']=True
        self.assertEqual(plan(d)['status'],'INVIABLE')
    def test_fixed_can_stay_when_rules_allow(self):
        d=fixture(2);d['units'][0]['fixed']=True;d['paddocks'][0]['occupied_days']=0
        self.assertEqual(plan(d)['assignment']['g'],[1,1])
    def test_destinations(self):
        d=fixture(2);d['units'][0]['allowed'][2]=[False]*2
        self.assertEqual(plan(d)['assignment']['g'],[2,2])
    def test_compatibility(self):
        d=fixture(2);u=copy.deepcopy(d['units'][0]);u.update(id='b',group='b',animals=[3],incompatible=['g']);d['units'].append(u)
        r=plan(d)
        self.assertTrue(all(a!=b for a,b in zip(r['assignment']['g'],r['assignment']['b'])))
    def test_full_daily_replay_rest_and_stay(self):
        d=fixture(14);r=plan(d);self.assertIn(r['status'],['OPTIMO','FACTIBLE'])
        for p in d['paddocks']:
            active=p['id']==1;stay=p['occupied_days'];rest=p['rested_days']
            for dest in r['assignment']['g']:
                now=dest==p['id']
                if now and not active:self.assertGreaterEqual(rest,p['rest'])
                stay=(stay+1 if active else 1) if now else 0
                rest=0 if now else (1 if active else rest+1)
                self.assertLessEqual(stay,p['max_stay']);active=now
    def test_baseline_exposes_deficit(self):
        d=fixture();d['paddocks'][0]['stock']=21
        r=plan(d);self.assertTrue(any(x['deficit']>0 for x in r['baseline']))
    def test_negative_and_nan_rejected(self):
        for v in [-1,float('nan'),float('inf'),True]:
            d=fixture();d['paddocks'][0]['stock']=v
            with self.assertRaises(ValueError):validate(d)
    def test_duplicate_animals_rejected(self):
        d=fixture();d['units'][0]['animals']=[1,1]
        with self.assertRaises(ValueError):validate(d)
    def test_invalid_api_and_horizon(self):
        with app.test_client() as client:
            self.assertEqual(client.post('/rotation/plan',json={}).status_code,422)
            d=fixture();d['horizon']=100
            self.assertEqual(client.post('/rotation/plan',json=d).status_code,422)

if __name__=='__main__':unittest.main()
