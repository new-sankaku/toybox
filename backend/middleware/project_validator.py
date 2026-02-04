from functools import wraps
from flask import jsonify


def require_project(project_service):
    def decorator(f):
        @wraps(f)
        def decorated(*args,**kwargs):
            project_id=kwargs.get("project_id")
            if not project_id:
                return jsonify({"error":"project_id is required"}),400
            project=project_service.get_project(project_id)
            if not project:
                return jsonify({"error":"Project not found"}),404
            kwargs["project"]=project
            return f(*args,**kwargs)
        return decorated
    return decorator
