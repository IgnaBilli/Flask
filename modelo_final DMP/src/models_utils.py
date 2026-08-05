import numpy as np

class WeightedEnsemble:
    def __init__(self, lgb_model, xgb_model, cat_model, weights=(0.40, 0.35, 0.25)):
        self.lgb_model = lgb_model
        self.xgb_model = xgb_model
        self.cat_model = cat_model
        self.weights = weights

    def predict(self, X):
        p_lgb = self.lgb_model.predict(X)
        p_xgb = self.xgb_model.predict(X)
        p_cat = self.cat_model.predict(X)

        return self.weights[0] * p_lgb + self.weights[1] * p_xgb + self.weights[2] * p_cat
