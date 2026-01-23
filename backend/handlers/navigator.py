from flask import request, jsonify
from handlers.websocket import broadcast_navigator_message


def register_navigator_routes(app, sio):
    """Register navigator message routes."""

    @app.route('/api/navigator/message', methods=['POST'])
    def send_navigator_message():
        """
        Send a navigator message to clients.

        Request body:
        {
            "projectId": "project-1" or "global",
            "speaker": "オペレーター",
            "text": "メッセージ内容",
            "priority": "normal"  # optional: low, normal, high, critical
        }
        """
        data = request.get_json()

        if not data:
            return jsonify({"error": "Request body required"}), 400

        project_id = data.get('projectId', 'global')
        speaker = data.get('speaker', 'オペレーター')
        text = data.get('text')
        priority = data.get('priority', 'normal')

        if not text:
            return jsonify({"error": "text field is required"}), 400

        if priority not in ('low', 'normal', 'high', 'critical'):
            return jsonify({"error": "Invalid priority. Must be: low, normal, high, critical"}), 400

        broadcast_navigator_message(sio, project_id, speaker, text, priority)

        return jsonify({
            "success": True,
            "message": "Navigator message sent",
            "data": {
                "projectId": project_id,
                "speaker": speaker,
                "text": text,
                "priority": priority
            }
        })

    @app.route('/api/navigator/broadcast', methods=['POST'])
    def broadcast_system_message():
        """
        Broadcast a system-wide navigator message to all connected clients.

        Request body:
        {
            "text": "システムメッセージ",
            "priority": "high"  # optional
        }
        """
        data = request.get_json()

        if not data:
            return jsonify({"error": "Request body required"}), 400

        text = data.get('text')
        priority = data.get('priority', 'high')

        if not text:
            return jsonify({"error": "text field is required"}), 400

        broadcast_navigator_message(sio, 'global', 'システム', text, priority)

        return jsonify({
            "success": True,
            "message": "System broadcast sent"
        })
