from flask import Flask, jsonify
from openapi import get_openapi_json


def register_openapi_routes(app: Flask):
    @app.route("/api/openapi.json", methods=["GET"])
    def get_openapi_spec():
        return jsonify(get_openapi_json())
