from flask import Blueprint, request, jsonify

rotation_api = Blueprint('rotation', __name__)

@rotation_api.post('/rotation/recommendations')
def paddock_recommendations():
    from .paddock_engine import recommend, validate
    try:
        data = request.get_json()
        validate(data)
        if 'groups' in data:
            from .group_engine import recommend as group_recommend, validate_groups
            validate_groups(data)
            return jsonify(group_recommend(data['paddocks'], data['groups']))
        return jsonify(recommend(data['paddocks']))
    except (ValueError, TypeError) as error:
        return jsonify(error=str(error)), 422

@rotation_api.post('/rotation/validate-transfer')
def validate_group_transfer():
    from .paddock_engine import validate
    from .group_engine import validate_groups, validate_transfer
    try:
        data = request.get_json()
        validate(data)
        validate_groups(data)
        return jsonify(validate_transfer(data))
    except (ValueError, TypeError, KeyError) as error:
        return jsonify(error=str(error)), 422

@rotation_api.post('/rotation/plan')
def create_plan():
    try:
        from .planner import plan, validate
        data = request.get_json()
        validate(data)
        return jsonify(plan(data))
    except ImportError:
        return jsonify(error='Planificador no disponible.'), 503
    except (ValueError, KeyError, TypeError) as error:
        return jsonify(error=str(error)), 422
