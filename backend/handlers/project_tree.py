"""Project Tree API - プロジェクトのファイルツリー管理"""
import os
import io
import zipfile
from flask import Flask,jsonify,request,send_file
from werkzeug.utils import secure_filename
from services.project_service import ProjectService
from middleware.logger import get_logger


def register_project_tree_routes(app:Flask,project_service:ProjectService,output_folder:str):
    """Register project tree related routes"""

    os.makedirs(output_folder,exist_ok=True)

    def _build_tree_node(path:str,base_path:str)->dict:
        """Build a tree node recursively"""
        name=os.path.basename(path)
        rel_path=os.path.relpath(path,base_path)
        node_id=rel_path.replace(os.sep,'-').replace('.','_')

        if os.path.isdir(path):
            children=[]
            try:
                for child in sorted(os.listdir(path)):
                    child_path=os.path.join(path,child)
                                                       
                    if child.startswith('.') or child=='__pycache__':
                        continue
                    children.append(_build_tree_node(child_path,base_path))
            except PermissionError:
                pass

            return {
                "id":node_id,
                "name":name,
                "type":"directory",
                "path":"/"+rel_path.replace(os.sep,'/'),
                "children":children
            }
        else:
                           
            try:
                stat=os.stat(path)
                size=stat.st_size
            except Exception as e:
                get_logger().warning(f"Failed to get file size for {path}: {e}")
                size=0

                                 
            ext=os.path.splitext(name)[1].lower()
            mime_types={
                '.py':'text/x-python',
                '.js':'text/javascript',
                '.ts':'text/typescript',
                '.tsx':'text/typescript',
                '.jsx':'text/javascript',
                '.html':'text/html',
                '.css':'text/css',
                '.json':'application/json',
                '.md':'text/markdown',
                '.txt':'text/plain',
                '.png':'image/png',
                '.jpg':'image/jpeg',
                '.jpeg':'image/jpeg',
                '.gif':'image/gif',
                '.svg':'image/svg+xml',
                '.mp3':'audio/mpeg',
                '.wav':'audio/wav',
                '.ogg':'audio/ogg',
            }
            mime_type=mime_types.get(ext,'application/octet-stream')

            return {
                "id":node_id,
                "name":name,
                "type":"file",
                "path":"/"+rel_path.replace(os.sep,'/'),
                "size":size,
                "mimeType":mime_type,
                "modified":False
            }

    def _get_project_output_path(project_id:str)->str:
        """Get the output folder path for a project"""
        return os.path.join(output_folder,project_id)

    @app.route('/api/projects/<project_id>/tree',methods=['GET'])
    def get_project_tree(project_id:str):
        """Get the file tree for a project"""
        project=project_service.get_project(project_id)
        if not project:
            return jsonify({"error":"Project not found"}),404

        project_path=_get_project_output_path(project_id)

                                                                         
        if not os.path.exists(project_path):
            os.makedirs(project_path,exist_ok=True)
                                    
            for folder in ['src','assets','docs']:
                os.makedirs(os.path.join(project_path,folder),exist_ok=True)
                             
            readme_path=os.path.join(project_path,'README.md')
            with open(readme_path,'w',encoding='utf-8') as f:
                f.write(f"# {project.get('name', 'Project')}\n\n")
                f.write(f"{project.get('description', '')}\n")

        tree=_build_tree_node(project_path,project_path)
        tree["name"]="project-root"
        tree["path"]="/"
        tree["id"]="root"

        return jsonify(tree)

    @app.route('/api/projects/<project_id>/tree/download',methods=['GET'])
    def download_project_file(project_id:str):
        """Download a single file from the project"""
        project=project_service.get_project(project_id)
        if not project:
            return jsonify({"error":"Project not found"}),404

        file_path=request.args.get('path','')
        if not file_path:
            return jsonify({"error":"Path parameter is required"}),400

                                                      
        file_path=file_path.lstrip('/')
        project_path=_get_project_output_path(project_id)
        full_path=os.path.normpath(os.path.join(project_path,file_path))

                                                      
        if not full_path.startswith(os.path.normpath(project_path)):
            return jsonify({"error":"Invalid path"}),400

        if not os.path.exists(full_path):
            return jsonify({"error":"File not found"}),404

        if os.path.isdir(full_path):
            return jsonify({"error":"Cannot download directory"}),400

        return send_file(
            full_path,
            as_attachment=True,
            download_name=os.path.basename(full_path)
        )

    @app.route('/api/projects/<project_id>/tree/replace',methods=['POST'])
    def replace_project_file(project_id:str):
        """Replace a file in the project"""
        project=project_service.get_project(project_id)
        if not project:
            return jsonify({"error":"Project not found"}),404

        if'file' not in request.files:
            return jsonify({"error":"No file in request"}),400

        file=request.files['file']
        file_path=request.form.get('path','')

        if not file_path:
            return jsonify({"error":"Path parameter is required"}),400

                       
        file_path=file_path.lstrip('/')
        project_path=_get_project_output_path(project_id)
        full_path=os.path.normpath(os.path.join(project_path,file_path))

                                                      
        if not full_path.startswith(os.path.normpath(project_path)):
            return jsonify({"error":"Invalid path"}),400

                                        
        os.makedirs(os.path.dirname(full_path),exist_ok=True)

                       
        file.save(full_path)

        return jsonify({"success":True,"path":"/"+file_path})

    @app.route('/api/projects/<project_id>/tree/download-all',methods=['GET'])
    def download_project_all(project_id:str):
        """Download the entire project as a ZIP file"""
        project=project_service.get_project(project_id)
        if not project:
            return jsonify({"error":"Project not found"}),404

        project_path=_get_project_output_path(project_id)

        if not os.path.exists(project_path):
            return jsonify({"error":"Project folder not found"}),404

                                   
        memory_file=io.BytesIO()

        with zipfile.ZipFile(memory_file,'w',zipfile.ZIP_DEFLATED) as zf:
            for root,dirs,files in os.walk(project_path):
                                                         
                dirs[:]=[d for d in dirs if not d.startswith('.') and d!='__pycache__']

                for file in files:
                    if file.startswith('.'):
                        continue
                    file_path=os.path.join(root,file)
                    arcname=os.path.relpath(file_path,project_path)
                    zf.write(file_path,arcname)

        memory_file.seek(0)

        project_name=project.get('name','project').replace(' ','_')

        return send_file(
            memory_file,
            mimetype='application/zip',
            as_attachment=True,
            download_name=f"{project_name}.zip"
        )
