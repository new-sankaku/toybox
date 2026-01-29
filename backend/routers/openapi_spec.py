from fastapi import APIRouter
from fastapi.responses import JSONResponse
import json
import os

router=APIRouter()


@router.get("/openapi.json")
async def get_openapi_spec():
 spec_path=os.path.join(os.path.dirname(os.path.dirname(__file__)),"openapi","openapi.json")
 if os.path.exists(spec_path):
  with open(spec_path,"r",encoding="utf-8") as f:
   return json.load(f)
 return {"openapi":"3.0.0","info":{"title":"ToyBox API","version":"1.0.0"},"paths":{}}
