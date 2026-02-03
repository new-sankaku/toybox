from .base import Skill,SkillResult,SkillContext,SkillCategory,SkillParameter


class TaskProgressSkill(Skill):
 name="task_progress"
 description="タスクの進捗状況を報告します（on_progressコールバックを通じて通知）"
 category=SkillCategory.PROJECT
 parameters=[
  SkillParameter(name="progress",type="integer",description="進捗率（0-100）"),
  SkillParameter(name="message",type="string",description="進捗メッセージ"),
 ]

 def __init__(self):
  super().__init__()

 async def execute(self,context:SkillContext,**kwargs)->SkillResult:
  progress=kwargs.get("progress",0)
  message=kwargs.get("message","")
  if not isinstance(progress,int) or progress<0 or progress>100:
   return SkillResult(success=False,error="progress must be an integer between 0 and 100")
  if not message:
   return SkillResult(success=False,error="message is required")
  if context.on_progress:
   try:
    context.on_progress(progress,message)
   except Exception as e:
    return SkillResult(success=False,error=f"Progress callback failed: {e}")
  return SkillResult(success=True,output=f"Progress reported: {progress}% - {message}",metadata={"progress":progress,"message":message})
