"""
Asset Generator Module

シミュレーション用アセット生成を担当
"""

import os
import uuid
import random
from datetime import datetime
from typing import Callable,Dict,List,Optional

from repositories import AssetRepository,ProjectRepository
from config_loaders.agent_config import get_agent_assets
from asset_scanner import get_testdata_path
from events.event_bus import EventBus
from events.events import AssetCreated
from middleware.logger import get_logger


class AssetGenerator:
    def __init__(
        self,
        event_bus:EventBus,
        add_system_log_func:Callable,
        increment_generation_count_func:Callable,
    ):
        self._event_bus=event_bus
        self._add_system_log=add_system_log_func
        self._increment_generation_count=increment_generation_count_func
        self._logger=get_logger()

    def check_asset_generation(
        self,
        session,
        agent,
        old_progress:int,
        new_progress:int,
    )->None:
        asset_points=self._get_asset_points(agent.type)
        for point_progress,asset_type,asset_name,asset_size in asset_points:
            if old_progress<point_progress<=new_progress:
                asset_repo=AssetRepository(session)
                display_name=(
                    agent.metadata_.get("displayName",agent.type)
                    if agent.metadata_
                    else agent.type
                )
                existing=[
                    a
                    for a in asset_repo.get_by_project(agent.project_id)
                    if a["name"]==asset_name and a["agent"]==display_name
                ]
                if not existing:
                    self._create_asset(
                        session,agent,asset_type,asset_name,asset_size
                    )
                    self._increment_generation_count(
                        session,agent.type,agent.project_id
                    )

    def _should_auto_approve_asset(
        self,session,project_id:str,asset_type:str
    )->bool:
        proj_repo=ProjectRepository(session)
        project=proj_repo.get(project_id)
        if not project:
            return False
        rules=(project.config or {}).get("autoApprovalRules",[])
        if not rules:
            return False
        for rule in rules:
            if rule.get("category")==asset_type:
                return rule.get("enabled",False)
        return False

    def _create_asset(
        self,
        session,
        agent,
        asset_type:str,
        name:str,
        size:str,
    )->None:
        testdata_path=get_testdata_path()
        real_file=self._find_real_file(
            session,testdata_path,asset_type,agent.project_id
        )
        display_name=(
            agent.metadata_.get("displayName",agent.type)
            if agent.metadata_
            else agent.type
        )
        actual_type=real_file["type"] if real_file else asset_type
        auto_approve=self._should_auto_approve_asset(
            session,agent.project_id,actual_type
        )
        approval_status="approved" if auto_approve else"pending"
        from models.tables import Asset

        if real_file:
            asset=Asset(
                id=f"asset-{uuid.uuid4().hex[:8]}",
                project_id=agent.project_id,
                agent_id=agent.id,
                name=real_file["name"],
                type=real_file["type"],
                agent=display_name,
                size=real_file["size"],
                url=real_file["url"],
                thumbnail=real_file["thumbnail"],
                duration=self._random_duration() if real_file["type"]=="audio" else None,
                approval_status=approval_status,
                created_at=datetime.now(),
            )
            log_msg=f"アセット生成: {real_file['name']}"+(
                " (自動承認)" if auto_approve else""
            )
            self._add_system_log(
                session,agent.project_id,"info",display_name,log_msg
            )
        else:
            url=f"/assets/{name}" if asset_type in ("image","audio") else None
            thumbnail=f"/thumbnails/{name}" if asset_type=="image" else None
            asset=Asset(
                id=f"asset-{uuid.uuid4().hex[:8]}",
                project_id=agent.project_id,
                agent_id=agent.id,
                name=name,
                type=asset_type,
                agent=display_name,
                size=size,
                url=url,
                thumbnail=thumbnail,
                duration=self._random_duration() if asset_type=="audio" else None,
                approval_status=approval_status,
                created_at=datetime.now(),
            )
            log_msg=f"アセット生成: {name}"+(" (自動承認)" if auto_approve else"")
            self._add_system_log(
                session,agent.project_id,"info",display_name,log_msg
            )
        session.add(asset)
        session.flush()
        if not auto_approve:
            agent.status="waiting_approval"
            session.flush()
        asset_repo=AssetRepository(session)
        self._event_bus.publish(
            AssetCreated(
                project_id=agent.project_id,
                asset=asset_repo.to_dict(asset),
                auto_approved=auto_approve,
            )
        )

    def _find_real_file(
        self,
        session,
        testdata_path:str,
        asset_type:str,
        project_id:str,
    )->Optional[Dict]:
        subdir_map={"image":"image","audio":"mp3","video":"movie"}
        subdir=subdir_map.get(asset_type)
        if not subdir:
            return None
        scan_path=os.path.join(testdata_path,subdir)
        if not os.path.exists(scan_path):
            return None
        all_files=[]
        for root,dirs,files in os.walk(scan_path):
            for filename in files:
                file_path=os.path.join(root,filename)
                relative_path=os.path.relpath(file_path,testdata_path)
                all_files.append(
                    {
                        "path":file_path,
                        "name":filename,
                        "relative":relative_path.replace(os.sep,"/"),
                    }
                )
        if not all_files:
            return None
        asset_repo=AssetRepository(session)
        used_files=set(
            a["url"]
            for a in asset_repo.get_by_project(project_id)
            if a.get("url")
        )
        available=[
            f for f in all_files if f"/testdata/{f['relative']}" not in used_files
        ]
        if not available:
            available=all_files
        chosen=random.choice(available)
        try:
            stat=os.stat(chosen["path"])
            from asset_scanner import format_file_size,get_file_type

            file_type=get_file_type(chosen["name"])
            return {
                "name":chosen["name"],
                "type":file_type,
                "size":format_file_size(stat.st_size),
                "url":f"/testdata/{chosen['relative']}",
                "thumbnail":f"/testdata/{chosen['relative']}"
                if file_type=="image"
                else None,
            }
        except Exception as e:
            self._logger.debug(f"Error reading file stat: {chosen['path']}: {e}")
            return None

    def _random_duration(self)->str:
        seconds=random.randint(5,180)
        mins=seconds//60
        secs=seconds%60
        return f"{mins}:{secs:02d}"

    def _get_asset_points(self,agent_type:str)->List[tuple]:
        assets=get_agent_assets(agent_type)
        return [
            (
                a.get("progress",0),
                a.get("type","document"),
                a.get("name",""),
                a.get("size",""),
            )
            for a in assets
        ]
