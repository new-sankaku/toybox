"""Mora列のAlignment

正解Mora列と認識Mora列を編集距離で対応付け、どのMoraで崩れたかを特定する。
Overlayでの誤り位置表示と、Localization指標の算出根拠になる。
"""
from dataclasses import dataclass
from typing import List,Optional,Sequence

MATCH="match"
SUBSTITUTE="substitute"
DELETE="delete"
INSERT="insert"


@dataclass(frozen=True)
class AlignOp:
 op:str
 ref_index:Optional[int]
 hyp_index:Optional[int]


@dataclass(frozen=True)
class Alignment:
 distance:float
 ops:List[AlignOp]


@dataclass(frozen=True)
class PrefixAlignment:
 distance:float
 ops:List[AlignOp]
 consumed:int
 skipped:int=0


def _table(
 reference:Sequence[str],
 hypothesis:Sequence[str],
 substitution_cost:float,
 deletion_cost:float,
 insertion_cost:float,
 restart_cost:Optional[float]=None,
)->List[List[float]]:
 n=len(reference)
 m=len(hypothesis)
 dp=[[0.0]*(m+1) for _ in range(n+1)]
 for i in range(1,n+1):
  dp[i][0]=dp[i-1][0]+deletion_cost
 for j in range(1,m+1):
  dp[0][j]=dp[0][j-1]+insertion_cost
  if restart_cost is not None:
   dp[0][j]=min(dp[0][j],restart_cost)
 for i in range(1,n+1):
  for j in range(1,m+1):
   if reference[i-1]==hypothesis[j-1]:
    dp[i][j]=dp[i-1][j-1]
    continue
   dp[i][j]=min(
    dp[i-1][j-1]+substitution_cost,
    dp[i-1][j]+deletion_cost,
    dp[i][j-1]+insertion_cost,
   )
 return dp


def _traceback(
 dp:List[List[float]],
 reference:Sequence[str],
 hypothesis:Sequence[str],
 start_i:int,
 start_j:int,
 substitution_cost:float,
 deletion_cost:float,
)->List[AlignOp]:
 ops:List[AlignOp]=[]
 i,j=start_i,start_j
 while i>0 or j>0:
  if i>0 and j>0 and reference[i-1]==hypothesis[j-1] and dp[i][j]==dp[i-1][j-1]:
   ops.append(AlignOp(MATCH,i-1,j-1))
   i-=1
   j-=1
  elif i>0 and j>0 and dp[i][j]==dp[i-1][j-1]+substitution_cost:
   ops.append(AlignOp(SUBSTITUTE,i-1,j-1))
   i-=1
   j-=1
  elif i>0 and dp[i][j]==dp[i-1][j]+deletion_cost:
   ops.append(AlignOp(DELETE,i-1,None))
   i-=1
  else:
   ops.append(AlignOp(INSERT,None,j-1))
   j-=1
 ops.reverse()
 return ops


def align(
 reference:Sequence[str],
 hypothesis:Sequence[str],
 substitution_cost:float=1.0,
 deletion_cost:float=1.0,
 insertion_cost:float=1.0,
)->Alignment:
 """正解列と認識列をAlignmentし、距離と操作列を返す"""
 dp=_table(reference,hypothesis,substitution_cost,deletion_cost,insertion_cost)
 ops=_traceback(
  dp,reference,hypothesis,len(reference),len(hypothesis),substitution_cost,deletion_cost
 )
 return Alignment(distance=dp[len(reference)][len(hypothesis)],ops=ops)


def align_prefix(
 reference:Sequence[str],
 hypothesis:Sequence[str],
 substitution_cost:float=1.0,
 deletion_cost:float=1.0,
 insertion_cost:float=1.0,
 restart_cost:Optional[float]=None,
)->PrefixAlignment:
 """発話途中の認識列を、正解列の先頭部分に対してAlignmentする

 正解列の末尾側は未発話として距離に加算しない。発話中のMora点灯に使う。

 restart_costを与えると、認識列の先頭側を一定Costで読み飛ばせる。
 言い淀みや言い直しで先頭に余分な発話が乗っても、それを全て挿入として
 数えずに済む。読み飛ばした数はskippedで返す。
 """
 dp=_table(reference,hypothesis,substitution_cost,deletion_cost,insertion_cost,restart_cost)
 column=len(hypothesis)
 best=min(dp[index][column] for index in range(len(reference)+1))
 consumed=max(
  index for index in range(len(reference)+1) if dp[index][column]==best
 )
 ops=_traceback(
  dp,reference,hypothesis,consumed,column,substitution_cost,deletion_cost
 )
 skipped=0
 for op in ops:
  if op.op!=INSERT:
   break
  skipped+=1
 return PrefixAlignment(
  distance=dp[consumed][column],ops=ops,consumed=consumed,skipped=skipped
 )
