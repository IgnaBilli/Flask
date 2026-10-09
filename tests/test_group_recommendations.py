import copy
import random
import unittest
from flask import Flask
from rotation import rotation_api
from rotation.group_engine import recommend, validate_transfer, validate_groups

def animal(i, category='NOVILLO', demand=10, condition=3):
    return dict(id=i, category=category, sex='F' if category in ('VACA','VAQUILLONA') else 'M', demand=demand, condition=condition)

def group(i, origin, animals, **kw):
    return dict(id=f'g{i}', configId=f'g{i}', name=f'Grupo {i}', origin=origin, animals=animals, allowSplit=kw.get('allowSplit',False), motherCalf=kw.get('motherCalf',False), isolated=kw.get('isolated',False),issues=kw.get('issues',[]))

def paddock(i, animals=0, demand=0, capacity=0, **kw):
    return dict(id=i,name=f'P{i}',stock=capacity*7,growth=0,demand=demand,animals=animals,included=True,enabled=True,issues=[],management=kw.get('management',{}))|{k:v for k,v in kw.items() if k!='management'}

class GroupTests(unittest.TestCase):
    def setUp(self):
        app=Flask(__name__);app.register_blueprint(rotation_api);self.client=app.test_client()

    def call(self, ps, gs):
        before=copy.deepcopy((ps,gs))
        r=self.client.post('/rotation/recommendations',json=dict(paddocks=ps,groups=gs))
        self.assertEqual(r.status_code,200,r.json)
        self.assertEqual((ps,gs),before)
        return r.json

    def test_whole_group_cannot_be_split_by_available_capacity(self):
        gs=[group(1,1,[animal(1),animal(2)])]
        ps=[paddock(1,2,20),paddock(2,capacity=12),paddock(3,capacity=12)]
        r=self.call(ps,gs)
        self.assertEqual(r['totals']['allocated'],0)
        gs[0]['allowSplit']=True
        r=self.call(ps,gs)
        self.assertEqual(r['totals']['allocated'],2)
        self.assertEqual(len(r['recommendations'][0]['destinations']),2)

    def test_bulls_females_require_service_and_calves_never_mix(self):
        gs=[group(1,1,[animal(1,'TORO')]),group(2,2,[animal(2,'VACA')])]
        ps=[paddock(1,1,10),paddock(2,1,10,capacity=30)]
        self.assertEqual(self.call(ps,gs)['totals']['allocated'],0)
        ps[1]['management']={'service':True}
        self.assertEqual(self.call(ps,gs)['totals']['allocated'],1)
        gs[1]['animals'][0]['category']='TERNERO'
        self.assertEqual(self.call(ps,gs)['totals']['allocated'],0)

    def test_projection_checks_incoming_groups_not_only_current_residents(self):
        gs=[group(1,1,[animal(1,'TORO')]),group(2,2,[animal(2,'VACA')])]
        ps=[paddock(1,1,10),paddock(2,1,10),paddock(3,capacity=100)]
        self.assertEqual(self.call(ps,gs)['totals']['allocated'],1)

    def test_category_and_isolation_constraints(self):
        gs=[group(1,1,[animal(1)],isolated=True),group(2,2,[animal(2)])]
        ps=[paddock(1,1,10),paddock(2,1,10,100),paddock(3,capacity=100,management={'categories':['VACA']})]
        self.assertEqual(self.call(ps,gs)['totals']['allocated'],0)
        ps[2]['management']={'categories':['NOVILLO']}
        self.assertEqual(self.call(ps,gs)['recommendations'][0]['destinations'][0]['id'],3)

    def test_body_condition_changes_competition_inside_same_urgency(self):
        gs=[group(1,1,[animal(1,condition=4)]),group(2,2,[animal(2,condition=2)])]
        ps=[paddock(1,1,10),paddock(2,1,10),paddock(3,capacity=12)]
        r=self.call(ps,gs)
        self.assertEqual(r['recommendations'][0]['origin'],2)
        self.assertEqual(r['recommendations'][0]['allocated'],1)
        gs[0]['animals'][0]['condition']=1
        self.assertEqual(self.call(ps,gs)['recommendations'][0]['origin'],1)

    def test_missing_condition_is_explicit_and_missing_demand_blocks(self):
        gs=[group(1,1,[animal(1,condition=None)])]
        ps=[paddock(1,1,10),paddock(2,capacity=20)]
        r=self.call(ps,gs)['recommendations'][0]
        self.assertEqual(r['missingCondition'],1);self.assertIsNone(r['condition'])
        gs[0]['animals'][0]['demand']=None
        self.assertEqual(self.call(ps,gs)['totals']['allocated'],0)

    def test_group_demand_is_not_paddock_average(self):
        gs=[group(1,1,[animal(1,demand=20,condition=2)]),group(2,1,[animal(2,demand=5)])]
        ps=[paddock(1,2,25,capacity=20),paddock(2,capacity=6)]
        r=self.call(ps,gs)
        self.assertEqual(len(r['recommendations']),1)
        self.assertEqual(r['recommendations'][0]['destinations'][0]['animalIds'],[2])
        self.assertEqual(r['totals']['pending'],0)

    def test_no_destination_does_not_claim_every_group_must_leave(self):
        gs=[group(1,1,[animal(1)]),group(2,1,[animal(2)])]
        r=self.call([paddock(1,2,20,capacity=15)],gs)
        self.assertEqual(r['totals']['toMove'],1)

    def test_split_group_tries_a_lighter_member_when_first_cannot_fit(self):
        gs=[group(1,1,[animal(1,demand=20,condition=2),animal(2,demand=5)],allowSplit=True)]
        r=self.call([paddock(1,2,25,capacity=20),paddock(2,capacity=6)],gs)
        self.assertEqual(r['recommendations'][0]['destinations'][0]['animalIds'],[2])
        self.assertEqual(r['totals']['pending'],0)

    def test_closed_origin_evacuates_all_even_excluded(self):
        gs=[group(1,1,[animal(1),animal(2)])]
        ps=[paddock(1,2,20,enabled=False,included=False,stock=None,growth=None),paddock(2,capacity=30)]
        r=self.call(ps,gs);self.assertEqual(r['totals']['allocated'],2)

    def test_mother_calf_cannot_split_even_payload_forged(self):
        gs=[group(1,1,[animal(1,'VACA'),animal(2,'TERNERO')],motherCalf=True,allowSplit=True)]
        with self.assertRaises(ValueError):validate_groups(dict(paddocks=[paddock(1,2,20)],groups=gs))

    def test_transfer_rechecks_category_service_and_membership(self):
        gs=[group(1,1,[animal(1),animal(2)])]
        body=dict(paddocks=[paddock(1,2,20),paddock(2,capacity=30)],groups=gs,
            transfer=dict(origin=1,destination=2,animalIds=[1,2],recommendation=True))
        self.assertTrue(validate_transfer(body)['valid'])
        body['transfer']['animalIds']=[1]
        with self.assertRaisesRegex(ValueError,'completo'):validate_transfer(body)
        body['transfer']['animalIds']=[1,2]
        body['paddocks'][1]['stock']=70
        with self.assertRaisesRegex(ValueError,'capacidad'):validate_transfer(body)
        body['paddocks'][1]['stock']=210
        body['paddocks'][1]['management']={'categories':['VACA']}
        with self.assertRaisesRegex(ValueError,'categorías'):validate_transfer(body)

    def test_random_allocations_conserve_animals_capacity_and_no_duplicates(self):
        rng=random.Random(42)
        for _ in range(100):
            n=rng.randint(1,25)
            gs=[group(1,1,[animal(i+1,demand=rng.randint(2,25)) for i in range(n)],allowSplit=bool(rng.randrange(2)))]
            demand=sum(a['demand'] for a in gs[0]['animals'])
            ps=[paddock(1,n,demand,capacity=rng.randint(0,demand)),paddock(2,capacity=rng.randint(0,demand)),paddock(3,capacity=rng.randint(0,demand))]
            r=self.call(ps,gs)
            self.assertEqual(sum(p['projectedAnimals'] for p in r['paddocks']),n)
            moved=[i for rec in r['recommendations'] for d in rec['destinations'] for i in d['animalIds']]
            self.assertEqual(len(moved),len(set(moved)))
            for p in r['paddocks'][1:]:self.assertLessEqual(p['projectedDemand'],p['capacity']+.01)
            for p in r['paddocks'][1:]:
                after_arrival_capacity=max(0,p['stock']-p['arrivalReserve'])/7+p['growth']
                self.assertLessEqual(p['projectedDemand'],after_arrival_capacity+.01)
            self.assertEqual(r['totals']['toMove'],r['totals']['allocated']+r['totals']['pending'])

    def test_arrival_day_consumption_cannot_overfill_destination_after_refresh(self):
        # Production reproduction: 40 incoming novillos fit a seven-day budget,
        # but no longer fit once the same-day transfer is charged to its stock.
        gs=[group(1,1,[animal(i+1,demand=8.53) for i in range(1001)],allowSplit=True),
            group(2,2,[animal(2000+i,'TERNERO',3.69) for i in range(3)],allowSplit=True)]
        ps=[paddock(1,1001,8538.53),paddock(2,3,11.07,stock=1996.7,growth=73.2)]
        r=self.call(ps,gs)
        dest=r['recommendations'][0]['destinations'][0]
        self.assertEqual(dest['quantity'],35)
        moved=set(dest['animalIds'])
        after_ps=copy.deepcopy(ps);after_gs=copy.deepcopy(gs)
        incoming=[a for a in after_gs[0]['animals'] if a['id'] in moved]
        after_gs[0]['animals']=[a for a in after_gs[0]['animals'] if a['id'] not in moved]
        after_gs.append(group(3,2,incoming,allowSplit=True))
        after_ps[0].update(animals=966,demand=966*8.53)
        after_ps[1].update(animals=38,demand=11.07+35*8.53,stock=1996.7-35*8.53)
        updated=self.call(after_ps,after_gs)
        self.assertNotEqual(updated['paddocks'][1]['status'],'EXCESO')
        body=dict(paddocks=ps,groups=gs,transfer=dict(origin=1,destination=2,animalIds=list(moved),recommendation=True))
        self.assertTrue(validate_transfer(body)['valid'])
        body['transfer']['animalIds']=list(range(1,41))
        with self.assertRaisesRegex(ValueError,'capacidad'):validate_transfer(body)

if __name__=='__main__':unittest.main()
