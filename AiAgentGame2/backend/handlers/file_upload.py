import os
import uuid
from flask import Flask, request, jsonify, send_from_directory
from werkzeug.utils import secure_filename
from testdata import TestDataStore

ALLOWED_EXTENSIONS = {
    # Code
    'txt', 'md', 'py', 'js', 'ts', 'jsx', 'tsx', 'html', 'css', 'json', 'xml', 'yaml', 'yml',
    'java', 'c', 'cpp', 'h', 'cs', 'go', 'rs', 'rb', 'php', 'swift', 'kt',
    # Images
    'png', 'jpg', 'jpeg', 'gif', 'webp', 'svg', 'bmp', 'ico',
    # Audio
    'mp3', 'wav', 'ogg', 'flac', 'aac', 'm4a', 'wma',
    # Video
    'mp4', 'webm', 'mov', 'avi', 'mkv', 'wmv',
    # Documents
    'pdf',
    # Archives
    'zip', 'tar', 'gz', 'tgz', '7z', 'rar',
}

CATEGORY_MAP = {
    # Code
    'txt': 'document', 'md': 'document', 'pdf': 'document',
    'py': 'code', 'js': 'code', 'ts': 'code', 'jsx': 'code', 'tsx': 'code',
    'html': 'code', 'css': 'code', 'json': 'code', 'xml': 'code', 'yaml': 'code', 'yml': 'code',
    'java': 'code', 'c': 'code', 'cpp': 'code', 'h': 'code', 'cs': 'code',
    'go': 'code', 'rs': 'code', 'rb': 'code', 'php': 'code', 'swift': 'code', 'kt': 'code',
    # Images
    'png': 'image', 'jpg': 'image', 'jpeg': 'image', 'gif': 'image',
    'webp': 'image', 'svg': 'image', 'bmp': 'image', 'ico': 'image',
    # Audio
    'mp3': 'audio', 'wav': 'audio', 'ogg': 'audio', 'flac': 'audio',
    'aac': 'audio', 'm4a': 'audio', 'wma': 'audio',
    # Video
    'mp4': 'video', 'webm': 'video', 'mov': 'video', 'avi': 'video',
    'mkv': 'video', 'wmv': 'video',
    # Archives
    'zip': 'archive', 'tar': 'archive', 'gz': 'archive', 'tgz': 'archive',
    '7z': 'archive', 'rar': 'archive',
}

MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB


def allowed_file(filename: str) -> bool:
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def get_category(filename: str) -> str:
    if '.' not in filename:
        return 'other'
    ext = filename.rsplit('.', 1)[1].lower()
    return CATEGORY_MAP.get(ext, 'other')


def get_mime_type(filename: str) -> str:
    ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
    mime_types = {
        # Code/Text
        'txt': 'text/plain', 'md': 'text/markdown', 'json': 'application/json',
        'py': 'text/x-python', 'js': 'text/javascript', 'ts': 'text/typescript',
        'html': 'text/html', 'css': 'text/css', 'xml': 'application/xml',
        # Images
        'png': 'image/png', 'jpg': 'image/jpeg', 'jpeg': 'image/jpeg',
        'gif': 'image/gif', 'webp': 'image/webp', 'svg': 'image/svg+xml',
        # Audio
        'mp3': 'audio/mpeg', 'wav': 'audio/wav', 'ogg': 'audio/ogg',
        'flac': 'audio/flac', 'm4a': 'audio/mp4',
        # Video
        'mp4': 'video/mp4', 'webm': 'video/webm', 'mov': 'video/quicktime',
        # Document
        'pdf': 'application/pdf',
    }
    return mime_types.get(ext, 'application/octet-stream')


def register_file_upload_routes(app: Flask, data_store: TestDataStore, upload_folder: str):
    os.makedirs(upload_folder, exist_ok=True)

    @app.route('/api/projects/<project_id>/files', methods=['GET'])
    def list_uploaded_files(project_id: str):
        project = data_store.get_project(project_id)
        if not project:
            return jsonify({"error": "Project not found"}), 404

        files = data_store.get_uploaded_files_by_project(project_id)
        return jsonify(files)

    @app.route('/api/projects/<project_id>/files', methods=['POST'])
    def upload_file(project_id: str):
        project = data_store.get_project(project_id)
        if not project:
            return jsonify({"error": "Project not found"}), 404

        if 'file' not in request.files:
            return jsonify({"error": "No file part in request"}), 400

        file = request.files['file']
        if file.filename == '':
            return jsonify({"error": "No selected file"}), 400

        if not allowed_file(file.filename):
            return jsonify({"error": f"File type not allowed. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}"}), 400

        # Check file size
        file.seek(0, 2)
        file_size = file.tell()
        file.seek(0)

        if file_size > MAX_FILE_SIZE:
            return jsonify({"error": f"File too large. Max size: {MAX_FILE_SIZE // (1024 * 1024)}MB"}), 400

        # Generate unique filename
        original_filename = secure_filename(file.filename)
        file_id = uuid.uuid4().hex[:12]
        ext = original_filename.rsplit('.', 1)[1].lower() if '.' in original_filename else ''
        stored_filename = f"{file_id}.{ext}" if ext else file_id

        # Save file
        project_folder = os.path.join(upload_folder, project_id)
        os.makedirs(project_folder, exist_ok=True)
        file_path = os.path.join(project_folder, stored_filename)
        file.save(file_path)

        # Get description from form data
        description = request.form.get('description', '')

        # Create file record
        uploaded_file = data_store.create_uploaded_file(
            project_id=project_id,
            filename=stored_filename,
            original_filename=original_filename,
            mime_type=get_mime_type(original_filename),
            category=get_category(original_filename),
            size_bytes=file_size,
            description=description
        )

        return jsonify(uploaded_file), 201

    @app.route('/api/projects/<project_id>/files/batch', methods=['POST'])
    def upload_files_batch(project_id: str):
        project = data_store.get_project(project_id)
        if not project:
            return jsonify({"error": "Project not found"}), 404

        if 'files' not in request.files:
            return jsonify({"error": "No files in request"}), 400

        files = request.files.getlist('files')
        if not files:
            return jsonify({"error": "No files selected"}), 400

        results = []
        errors = []

        for file in files:
            if file.filename == '':
                continue

            if not allowed_file(file.filename):
                errors.append({
                    "filename": file.filename,
                    "error": "File type not allowed"
                })
                continue

            # Check file size
            file.seek(0, 2)
            file_size = file.tell()
            file.seek(0)

            if file_size > MAX_FILE_SIZE:
                errors.append({
                    "filename": file.filename,
                    "error": f"File too large (max {MAX_FILE_SIZE // (1024 * 1024)}MB)"
                })
                continue

            # Generate unique filename
            original_filename = secure_filename(file.filename)
            file_id = uuid.uuid4().hex[:12]
            ext = original_filename.rsplit('.', 1)[1].lower() if '.' in original_filename else ''
            stored_filename = f"{file_id}.{ext}" if ext else file_id

            # Save file
            project_folder = os.path.join(upload_folder, project_id)
            os.makedirs(project_folder, exist_ok=True)
            file_path = os.path.join(project_folder, stored_filename)
            file.save(file_path)

            # Create file record
            uploaded_file = data_store.create_uploaded_file(
                project_id=project_id,
                filename=stored_filename,
                original_filename=original_filename,
                mime_type=get_mime_type(original_filename),
                category=get_category(original_filename),
                size_bytes=file_size,
                description=""
            )
            results.append(uploaded_file)

        return jsonify({
            "success": results,
            "errors": errors,
            "totalUploaded": len(results),
            "totalErrors": len(errors)
        }), 201 if results else 400

    @app.route('/api/files/<file_id>', methods=['GET'])
    def get_uploaded_file_info(file_id: str):
        file_record = data_store.get_uploaded_file(file_id)
        if not file_record:
            return jsonify({"error": "File not found"}), 404
        return jsonify(file_record)

    @app.route('/api/files/<file_id>', methods=['DELETE'])
    def delete_uploaded_file(file_id: str):
        file_record = data_store.get_uploaded_file(file_id)
        if not file_record:
            return jsonify({"error": "File not found"}), 404

        # Delete physical file
        project_folder = os.path.join(upload_folder, file_record["projectId"])
        file_path = os.path.join(project_folder, file_record["filename"])
        if os.path.exists(file_path):
            os.remove(file_path)

        # Delete record
        data_store.delete_uploaded_file(file_id)

        return jsonify({"success": True})

    @app.route('/api/files/<file_id>/download', methods=['GET'])
    def download_file(file_id: str):
        file_record = data_store.get_uploaded_file(file_id)
        if not file_record:
            return jsonify({"error": "File not found"}), 404

        project_folder = os.path.join(upload_folder, file_record["projectId"])
        return send_from_directory(
            project_folder,
            file_record["filename"],
            download_name=file_record["originalFilename"],
            as_attachment=True
        )

    @app.route('/uploads/<project_id>/<filename>', methods=['GET'])
    def serve_uploaded_file(project_id: str, filename: str):
        project_folder = os.path.join(upload_folder, project_id)
        return send_from_directory(project_folder, filename)
