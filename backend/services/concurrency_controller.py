import threading
from typing import Dict,Optional,Protocol
from middleware.logger import get_logger


class ConcurrencyConfigProvider(Protocol):
    def get_provider_max_concurrent(self,provider_id:str)->int:
        ...
    def get_provider_group(self,provider_id:str)->Optional[str]:
        ...
    def get_group_max_concurrent(self,group_id:str)->int:
        ...


class DefaultConcurrencyConfig:
    def get_provider_max_concurrent(self,provider_id:str)->int:
        from config_loaders.ai_provider_config import get_provider_max_concurrent
        return get_provider_max_concurrent(provider_id)

    def get_provider_group(self,provider_id:str)->Optional[str]:
        from config_loaders.ai_provider_config import get_provider_group
        return get_provider_group(provider_id)

    def get_group_max_concurrent(self,group_id:str)->int:
        from config_loaders.ai_provider_config import get_group_max_concurrent
        return get_group_max_concurrent(group_id)


class ConcurrencyController:
    def __init__(self,config:Optional[ConcurrencyConfigProvider]=None):
        self._config=config or DefaultConcurrencyConfig()
        self._active_jobs_by_provider:Dict[str,Dict[str,bool]]={}
        self._active_jobs_by_group:Dict[str,Dict[str,bool]]={}
        self._lock=threading.Lock()

    def get_provider_active_count(self,provider_id:str)->int:
        with self._lock:
            provider_jobs=self._active_jobs_by_provider.get(provider_id,{})
            return sum(1 for active in provider_jobs.values() if active)

    def get_group_active_count(self,group_id:str)->int:
        with self._lock:
            group_jobs=self._active_jobs_by_group.get(group_id,{})
            return sum(1 for active in group_jobs.values() if active)

    def can_start_job(self,provider_id:str,job_id:str)->bool:
        with self._lock:
            if job_id in self._active_jobs_by_provider.get(provider_id,{}):
                return False
            group_id=self._config.get_provider_group(provider_id)
            if group_id:
                group_max=self._config.get_group_max_concurrent(group_id)
                group_jobs=self._active_jobs_by_group.get(group_id,{})
                active_count=sum(1 for active in group_jobs.values() if active)
                if active_count>=group_max:
                    return False
            else:
                provider_max=self._config.get_provider_max_concurrent(provider_id)
                provider_jobs=self._active_jobs_by_provider.get(provider_id,{})
                active_count=sum(1 for active in provider_jobs.values() if active)
                if active_count>=provider_max:
                    return False
        return True

    def register_job(self,job_id:str,provider_id:str)->None:
        with self._lock:
            if provider_id not in self._active_jobs_by_provider:
                self._active_jobs_by_provider[provider_id]={}
            self._active_jobs_by_provider[provider_id][job_id]=True
            group_id=self._config.get_provider_group(provider_id)
            if group_id:
                if group_id not in self._active_jobs_by_group:
                    self._active_jobs_by_group[group_id]={}
                self._active_jobs_by_group[group_id][job_id]=True

    def unregister_job(self,job_id:str,provider_id:str)->None:
        with self._lock:
            if provider_id in self._active_jobs_by_provider:
                self._active_jobs_by_provider[provider_id].pop(job_id,None)
            group_id=self._config.get_provider_group(provider_id)
            if group_id and group_id in self._active_jobs_by_group:
                self._active_jobs_by_group[group_id].pop(job_id,None)

    def clear_all(self)->None:
        with self._lock:
            self._active_jobs_by_provider.clear()
            self._active_jobs_by_group.clear()
            get_logger().info("ConcurrencyController cleared all active jobs")
