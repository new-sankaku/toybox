from flask import Flask, request, jsonify
from testdata import TestDataStore


def register_checkpoint_routes(app: Flask, data_store: TestDataStore, sio):

    @app.route('/api/projects/<project_id>/checkpoints', methods=['GET'])
    def list_project_checkpoints(project_id: str):
        project = data_store.get_project(project_id)
        if not project:
            return jsonify({"error": "Project not found"}), 404

        checkpoints = data_store.get_checkpoints_by_project(project_id)
        return jsonify(checkpoints)

    @app.route('/api/checkpoints/<checkpoint_id>/resolve', methods=['POST'])
    def resolve_checkpoint(checkpoint_id: str):
        data = request.get_json() or {}
        resolution = data.get("resolution")  # approved, rejected, revision_requested
        feedback = data.get("feedback")

        if resolution not in ("approved", "rejected", "revision_requested"):
            return jsonify({"error": "Invalid resolution. Must be: approved, rejected, or revision_requested"}), 400

        checkpoint = data_store.resolve_checkpoint(checkpoint_id, resolution, feedback)

        if not checkpoint:
            return jsonify({"error": "Checkpoint not found"}), 404

        sio.emit('checkpoint:resolved', {
            "checkpointId": checkpoint_id,
            "projectId": checkpoint["projectId"],
            "agentId": checkpoint["agentId"],
            "resolution": resolution,
            "feedback": feedback
        })

        return jsonify(checkpoint)
