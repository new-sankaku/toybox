from datetime import datetime,timedelta


class DataRetentionPolicy:
    def __init__(self,retention_days:int=30):
        self._retention_days=retention_days

    @property
    def retention_days(self)->int:
        return self._retention_days

    @retention_days.setter
    def retention_days(self,days:int)->None:
        if days<1:
            raise ValueError("retention_days must be at least 1")
        self._retention_days=days

    def get_cutoff_date(self,days_override:int|None=None)->datetime:
        days=days_override if days_override is not None else self._retention_days
        return datetime.now()-timedelta(days=days)

    def is_expired(
        self,timestamp:datetime,days_override:int|None=None
    )->bool:
        cutoff=self.get_cutoff_date(days_override)
        return timestamp<cutoff
