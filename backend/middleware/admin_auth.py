import os
import functools
from flask import request,jsonify
from middleware.logger import get_logger


def get_admin_token()->str:
 return os.environ.get("ADMIN_TOKEN","")


def require_admin_auth(f):
 @functools.wraps(f)
 def decorated(*args,**kwargs):
  token=get_admin_token()
  if not token:
   get_logger().warning("ADMIN_TOKEN is not configured")
   return jsonify({"error":"Admin authentication is not configured"}),503
  auth_header=request.headers.get("Authorization","")
  if not auth_header.startswith("Bearer "):
   return jsonify({"error":"認証が必要です"}),401
  provided_token=auth_header[7:]
  if provided_token!=token:
   return jsonify({"error":"認証に失敗しました"}),401
  return f(*args,**kwargs)
 return decorated
