import copy
import unittest
from flask import Flask
from rotation import rotation_api
from rotation.fuzzy_priority import evaluate_priority
from rotation.paddock_engine import recommend

def p(id,stock=0,growth=0,animals=10,**kw):
    return dict(id=id,name=f'P{id}',stock=stock,growth=growth,animals=animals,demand=animals*10,included=True,issues=[],**kw)

class RecommendationTests(unittest.TestCase):
    def setUp(self):
        app=Flask(__name__);app.register_blueprint(rotation_api);self.client=app.test_client()

    def test_real_endpoint_and_priority_compete_for_shared_capacity(self):
        inputs=[p(1,0,95),p(2,670),p(3,70,animals=0)];before=copy.deepcopy(inputs)
        r=self.client.post('/rotation/recommendations',json={'paddocks':inputs})
        self.assertEqual(r.status_code,200);data=r.get_json()
        self.assertEqual(data['engineRuntime'],'python')
        self.assertEqual([x['origin'] for x in data['recommendations']],[2,1])
        self.assertEqual(data['totals']['allocated'],1);self.assertEqual(data['totals']['pending'],1)
        self.assertEqual(inputs,before)

    def test_closed_without_demand_and_missing_data(self):
        a=p(1,stock=None,growth=None,enabled=False);a['demand']=None
        data=recommend([a,p(2,700,animals=0)])
        self.assertTrue(data['partial']);self.assertEqual(data['totals']['pending'],10)
        self.assertIsNone(data['recommendations'][0]['priority'])

    def test_closed_excluded_still_evacuates_and_never_receives(self):
        a=p(1,10000,1000,enabled=False);a['included']=False
        data=recommend([a,p(2,700,animals=0),p(3,700,animals=0)])
        self.assertEqual(data['totals']['allocated'],10)
        self.assertEqual(data['paddocks'][0]['incoming'],0)
        self.assertEqual(sum(p['projectedAnimals'] for p in data['paddocks']),10)

    def test_empty_and_invalid_payloads(self):
        self.assertEqual(self.client.post('/rotation/recommendations',json={'paddocks':[]}).status_code,200)
        for body in [{},[],{'paddocks':[p(1),p(1)]},{'paddocks':[dict(p(1),animals=-1)]},
                     {'paddocks':[dict(p(1),growth='10')]},{'paddocks':[dict(p(1),included='false')]},
                     {'paddocks':[dict(p(1),stock=float('inf'))]}]:
            with self.subTest(body=body):self.assertEqual(self.client.post('/rotation/recommendations',json=body).status_code,422)

    def test_fuzzy_interpolation_and_zero_growth(self):
        self.assertEqual(evaluate_priority(p(1,500,100))['score'],55)
        self.assertEqual(len(evaluate_priority(p(1,500,100))['rules']),4)
        self.assertEqual(evaluate_priority(p(1))['level'],'ALTA')
        self.assertIsNone(evaluate_priority(dict(p(1),stock=None)))

    def test_monotonicity(self):
        for days in range(21):
            scores=[evaluate_priority(p(1,days*100,100/(i/10)))['score'] for i in range(1,31)]
            self.assertEqual(scores,sorted(scores))
        for ratio in range(1,31):
            scores=[evaluate_priority(p(1,days*100,100/(ratio/10)))['score'] for days in range(21)]
            self.assertEqual(scores,sorted(scores,reverse=True))

if __name__=='__main__':unittest.main()
